"""Short database transactions for immutable sources and period snapshots."""
import hashlib
import json
import unicodedata
from uuid import uuid4

from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_engine
from app.modules.company_observation.calendar import expected_weeks, periods_since
from app.modules.company_observation.sources import PARSER_VERSION, Resource

ANALYSIS_VERSION = 'name-keywords-v1'


def normalize(value: str) -> str:
    return unicodedata.normalize('NFKC', value).casefold()


def claim_collection() -> str | None:
    token = str(uuid4())
    with get_engine().begin() as conn:
        result = conn.execute(text('''
            INSERT INTO company_worker_state(name, claim_token, lease_until, last_attempt_at)
            VALUES ('sources', :token, now() + interval '10 minutes', now())
            ON CONFLICT(name) DO UPDATE SET claim_token=EXCLUDED.claim_token,
                lease_until=EXCLUDED.lease_until, last_attempt_at=now()
            WHERE company_worker_state.lease_until IS NULL OR company_worker_state.lease_until < now()
            RETURNING name
        '''), {'token': token}).first()
    return token if result else None


def renew_collection(token: str) -> None:
    with get_engine().begin() as conn:
        count = conn.execute(text('''
            UPDATE company_worker_state SET lease_until=now() + interval '10 minutes'
            WHERE name='sources' AND claim_token=:token AND lease_until>now()
        '''), {'token': token}).rowcount
    if not count:
        raise ValueError('collection_lease_lost')


def finish_collection(token: str, resources: list[Resource] | None, error: str | None) -> None:
    payload = json.dumps({'resource_ids': [item.id for item in resources]}) if resources else None
    with get_engine().begin() as conn:
        conn.execute(text('''
            UPDATE company_worker_state SET lease_until=NULL, error_code=:error,
                last_success_at=CASE WHEN :error IS NULL THEN now() ELSE last_success_at END,
                payload=COALESCE(CAST(:payload AS jsonb), payload)
            WHERE name='sources' AND claim_token=:token
        '''), {'token': token, 'error': error, 'payload': payload})


def save_source(resource: Resource, body: bytes, records: list[dict], diagnostics: dict,
                status: str, token: str) -> None:
    digest, file_id = hashlib.sha256(body).hexdigest(), str(uuid4())
    with get_engine().begin() as conn:
        owner = conn.execute(text('''SELECT name FROM company_worker_state
            WHERE name='sources' AND claim_token=:token AND lease_until>now() FOR UPDATE
        '''), {'token': token}).first()
        if not owner:
            raise ValueError('collection_lease_lost')
        inserted = conn.execute(text('''
            INSERT INTO company_source_files(id, resource_id, source_url, coverage_start,
                coverage_end_exclusive, content_sha256, raw_content, parser_version,
                published_date, status, diagnostics)
            VALUES (:id, :resource, :url, :start, :end, :sha, :raw, :parser,
                :published, :status, CAST(:diagnostics AS jsonb))
            ON CONFLICT(resource_id, content_sha256, parser_version) DO NOTHING RETURNING id
        '''), {'id': file_id, 'resource': resource.id, 'url': resource.url, 'start': resource.start,
              'end': resource.end, 'sha': digest, 'raw': body, 'parser': PARSER_VERSION,
              'published': resource.published_date, 'status': status,
              'diagnostics': json.dumps(diagnostics)}).first()
        if inserted and records:
            conn.execute(text('''
                INSERT INTO company_source_records(source_file_id, row_locator, company_key,
                    identifier_type, identifier_value, name_en, name_zh, incorporation_date,
                    event_type, error_code)
                VALUES (:source_file_id, :row_locator, :company_key, :identifier_type,
                    :identifier_value, :name_en, :name_zh, :incorporation_date, :event_type, :error_code)
            '''), [{'source_file_id': file_id, **record} for record in records])


def build_snapshots(resources: list[Resource], token: str) -> None:
    by_week = {item.start: item for item in resources}
    with get_engine().connect() as conn:
        files = conn.execute(text('''SELECT DISTINCT ON(resource_id) id, resource_id, source_url,
                coverage_start, coverage_end_exclusive, content_sha256, status, fetched_at,
                published_date, diagnostics FROM company_source_files
            WHERE parser_version=:version ORDER BY resource_id, fetched_at DESC
        '''), {'version': PARSER_VERSION}).mappings().all()
    by_resource = {row['resource_id']: dict(row) for row in files}
    for kind, start, end in periods_since(min(by_week)):
        renew_collection(token)
        selected, missing = [], []
        for week in expected_weeks(start, end):
            resource = by_week.get(week)
            file = by_resource.get(resource.id) if resource else None
            if file:
                selected.append(file)
                if file['status'] != 'complete':
                    missing.append({'start_date': week.isoformat(),
                                    'reason_code': file['diagnostics'].get('reason_code', 'source_invalid')})
            else:
                missing.append({'start_date': week.isoformat(), 'reason_code': 'source_missing'})
        create_snapshot(kind, start, end, selected, missing, token)


def source_info(file: dict) -> dict:
    return {'resource_id': file['resource_id'], 'source_url': file['source_url'],
            'coverage_start': file['coverage_start'].isoformat(),
            'coverage_end_exclusive': file['coverage_end_exclusive'].isoformat(),
            'fetched_at': file['fetched_at'].isoformat(),
            'published_date': file['published_date'].isoformat() if file['published_date'] else None,
            'status': file['status']}


def snapshot_companies(conn, selected: list[dict], start, end) -> tuple[dict, bool]:
    companies, conflict = {}, False
    for file in selected:
        rows = conn.execute(text('''SELECT id, company_key, name_en, name_zh, incorporation_date
            FROM company_source_records WHERE source_file_id=:file AND event_type='incorporation'
                AND error_code IS NULL AND incorporation_date>=:start AND incorporation_date<:end
            ORDER BY row_locator
        '''), {'file': file['id'], 'start': start, 'end': end}).mappings()
        for row in rows:
            key = row['company_key']
            if key in companies:
                old = companies[key]
                if any(row[field] != old[field] for field in ('name_en', 'name_zh', 'incorporation_date')):
                    conflict = True
            else:
                companies[key] = dict(row)
    return companies, conflict


def create_snapshot(kind, start, end, selected: list[dict], missing: list[dict], token: str) -> None:
    material = {'files': sorted(str(file['id']) for file in selected), 'missing': missing,
                'parser': PARSER_VERSION, 'matching': ANALYSIS_VERSION}
    fingerprint = hashlib.sha256(json.dumps(material, sort_keys=True).encode()).hexdigest()
    with get_engine().begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(72419202)'))
        owner = conn.execute(text('''SELECT name FROM company_worker_state WHERE name='sources'
            AND claim_token=:token AND lease_until>now() FOR UPDATE'''), {'token': token}).first()
        if not owner:
            raise ValueError('collection_lease_lost')
        current = conn.execute(text('''SELECT id, dataset_fingerprint FROM company_period_reports
            WHERE period_type=:kind AND start_date=:start AND is_current FOR UPDATE
        '''), {'kind': kind, 'start': start}).first()
        if current and current.dataset_fingerprint == fingerprint:
            return
        companies, conflict = snapshot_companies(conn, selected, start, end)
        if conflict:
            missing = [*missing, {'start_date': start.isoformat(), 'reason_code': 'identity_conflict'}]
        status = 'partial' if missing else 'complete'
        if not selected:
            status = 'unavailable'
        analysis = 'pending' if settings.deepseek_api_key.get_secret_value() else 'not_configured'
        if status != 'complete' or not companies:
            analysis = 'not_needed'
        report_id = str(uuid4())
        if current:
            conn.execute(text('''UPDATE company_period_reports SET is_current=false,
                analysis_status='superseded', claim_token=NULL, lease_until=NULL WHERE id=:id
            '''), {'id': current.id})
        existing = conn.execute(text('''SELECT id FROM company_period_reports WHERE period_type=:kind
            AND start_date=:start AND dataset_fingerprint=:fingerprint AND analysis_version=:version
        '''), {'kind': kind, 'start': start, 'fingerprint': fingerprint, 'version': ANALYSIS_VERSION}).first()
        if existing:
            conn.execute(text('''UPDATE company_period_reports SET is_current=true, analysis_status=:analysis,
                summary=NULL, attempt_count=0, retry_after=NULL WHERE id=:id'''),
                         {'id': existing.id, 'analysis': analysis})
            return
        conn.execute(text('''INSERT INTO company_period_reports(id, period_type, start_date,
            end_date_exclusive, dataset_fingerprint, analysis_version, data_status, analysis_status,
            observed_company_count, sources, missing_resources, error_code)
            VALUES (:id, :kind, :start, :end, :fingerprint, :version, :status, :analysis, :count,
                CAST(:sources AS jsonb), CAST(:missing AS jsonb), :error)
        '''), {'id': report_id, 'kind': kind, 'start': start, 'end': end, 'fingerprint': fingerprint,
              'version': ANALYSIS_VERSION, 'status': status, 'analysis': analysis, 'count': len(companies),
              'sources': json.dumps([source_info(file) for file in selected]),
              'missing': json.dumps(missing), 'error': missing[0]['reason_code'] if missing else None})
        if companies:
            conn.execute(text('''INSERT INTO company_report_companies(report_id, company_key,
                source_record_id, incorporation_date, search_name)
                VALUES (:report, :key, :source, :day, :search)
            '''), [{'report': report_id, 'key': key, 'source': row['id'],
                   'day': row['incorporation_date'], 'search': normalize(row['name_en'] + '\n' + row['name_zh'])}
                  for key, row in companies.items()])
