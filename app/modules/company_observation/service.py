import base64
import hashlib
import json
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.errors import AppError
from app.modules.company_observation.calendar import latest_ended, period_end, period_start, today
from app.modules.company_observation.schemas import (
    CompaniesResponse, Company, LiquidationsResponse, Overview, Period, PeriodsResponse, Topic,
)
from app.modules.company_observation.storage import ANALYSIS_VERSION, normalize


def period_data(row) -> dict:
    scope = 'incorporation_and_redomiciliation' if row['analysis_version'] == ANALYSIS_VERSION else 'incorporation'
    return {'report_id': row['id'], 'population_scope': scope, **{key: row[key] for key in
        ('period_type', 'start_date', 'end_date_exclusive', 'data_status', 'analysis_status', 'error_code')}}


def read_periods(session: Session, kind: str) -> PeriodsResponse:
    rows = session.execute(text('''SELECT * FROM company_period_reports
        WHERE period_type=:kind AND is_current ORDER BY start_date DESC
    '''), {'kind': kind}).mappings().all()
    default = next((row['start_date'] for row in rows if row['data_status'] == 'complete'),
                   rows[0]['start_date'] if rows else None)
    state = session.execute(text("SELECT * FROM company_worker_state WHERE name='sources'")).mappings().first()
    return PeriodsResponse(items=[Period(**period_data(row)) for row in rows],
                           default_start_date=default, latest_ended_start_date=latest_ended(kind),
                           last_success_at=state['last_success_at'] if state else None,
                           source_error_code=state['error_code'] if state else 'not_collected')


def current_report(session: Session, report_id: UUID):
    row = session.execute(text('SELECT * FROM company_period_reports WHERE id=:id'),
                          {'id': report_id}).mappings().first()
    if not row:
        raise AppError('http_404', 'Report not found', 404)
    if not row['is_current'] or row['analysis_status'] == 'superseded':
        raise AppError('report_superseded', 'Report superseded', 409)
    return row


def localized(display: dict, language: str) -> tuple[dict, str, bool]:
    requested = 'zh-Hant' if language == 'yue-Hant-HK' else language
    actual = requested if requested in display else 'zh-Hant'
    return display[actual], actual, actual != language


def topic_data(row, language: str) -> Topic:
    content, actual, fallback = localized(row['display'], language)
    return Topic(topic_id=row['topic_id'], report_id=row['report_id'], title=content['title'],
                 explanation=content['explanation'], company_count=row['company_count'],
                 content_language=actual, language_fallback=fallback, terms=row['rules'])


def read_overview(session: Session, kind: str, start: date | None, language: str) -> Overview:
    if start is None:
        start = read_periods(session, kind).default_start_date
    if start is None:
        raise AppError('http_404', 'No collected periods', 404)
    if start != period_start(kind, start) or start > latest_ended(kind):
        raise AppError('validation_error', 'Invalid period start', 422)
    row = session.execute(text('''SELECT * FROM company_period_reports WHERE period_type=:kind
        AND start_date=:start AND is_current'''), {'kind': kind, 'start': start}).mappings().first()
    if not row:
        raise AppError('http_404', 'Period not found', 404)
    published = row['analysis_status'] == 'published'
    topics = []
    summary, findings, actual, fallback = None, [], None, False
    if published:
        content, actual, fallback = localized(row['summary'], language)
        summary, findings = content['summary'], content['findings']
        topics = [topic_data(item, language) for item in session.execute(text('''
            SELECT * FROM company_report_topics WHERE report_id=:id ORDER BY sort_order
        '''), {'id': row['id']}).mappings()]
    unknown = row['unknown_company_count'] if published else None
    count = row['observed_company_count']
    retry_allowed = (row['analysis_status'] == 'failed'
        and row['attempt_count'] < settings.company_observation_max_analysis_attempts
        and row['data_status'] == 'complete' and count > 0
        and settings.company_observation_enabled and settings.company_observation_ai_enabled
        and row['analysis_version'] == ANALYSIS_VERSION
        and bool(settings.deepseek_api_key.get_secret_value()))
    return Overview(**period_data(row), dataset_fingerprint=row['dataset_fingerprint'],
        analysis_version=row['analysis_version'], analysis_attempt_count=row['attempt_count'],
        analysis_max_attempts=settings.company_observation_max_analysis_attempts,
        analysis_retry_after=row['retry_after'] if retry_allowed else None,
        analysis_retry_allowed=retry_allowed, observed_company_count=count,
        total_company_count=count if row['data_status'] == 'complete' else None,
        identified_company_count=row['identified_company_count'] if published else None,
        unknown_company_count=unknown, unknown_company_ratio=unknown / count if unknown is not None and count else None,
        summary=summary, findings=findings, content_language=actual, language_fallback=fallback,
        generated_at=row['generated_at'] if published else None, sources=row['sources'],
        missing_resources=row['missing_resources'], topics=topics)


def read_topic(session: Session, report_id: UUID, topic_id: str, language: str) -> Topic:
    report = current_report(session, report_id)
    if report['analysis_status'] != 'published':
        raise AppError('http_404', 'Topic unavailable', 404)
    row = session.execute(text('''SELECT * FROM company_report_topics
        WHERE report_id=:report AND topic_id=:topic'''), {'report': report_id, 'topic': topic_id}).mappings().first()
    if not row:
        raise AppError('http_404', 'Topic not found', 404)
    return topic_data(row, language)


def filter_digest(report_id, topic, query) -> str:
    return hashlib.sha256(json.dumps([str(report_id), topic, query], ensure_ascii=False).encode()).hexdigest()


def decode_cursor(cursor: str, binding: str) -> tuple[date, str]:
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
        if (set(value) != {'binding', 'date', 'key'} or value['binding'] != binding
                or not isinstance(value['key'], str) or len(value['key']) > 64):
            raise ValueError('Invalid cursor')
        return date.fromisoformat(value['date']), value['key']
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise AppError('validation_error', 'Invalid cursor', 422) from error


def read_companies(session: Session, report_id: UUID, topic_id: str | None,
                   query: str, cursor: str | None, limit: int) -> CompaniesResponse:
    report = current_report(session, report_id)
    if topic_id:
        read_topic(session, report_id, topic_id, 'zh-Hant')
    query = normalize(query.strip())
    binding = filter_digest(report_id, topic_id, query)
    after_date, after_key = decode_cursor(cursor, binding) if cursor else (None, None)
    # position() gives literal search semantics; %, _ and backslashes are ordinary text.
    rows = session.execute(text('''
        SELECT c.company_key, c.incorporation_date, r.identifier_type, r.identifier_value,
            r.name_en, r.name_zh, r.event_type, f.resource_id, f.source_url, f.coverage_start,
            f.coverage_end_exclusive, f.fetched_at, f.published_date, f.status,
            f.diagnostics->>'date_semantics' AS date_semantics,
            COALESCE(m.evidence, '[]'::jsonb) AS evidence
        FROM company_report_companies c JOIN company_source_records r ON r.id=c.source_record_id
        JOIN company_source_files f ON f.id=r.source_file_id
        LEFT JOIN company_topic_memberships m ON m.report_id=c.report_id
            AND m.company_key=c.company_key AND m.topic_id=:topic
        WHERE c.report_id=:report AND (:topic IS NULL OR m.topic_id IS NOT NULL)
            AND (:query='' OR position(:query IN c.search_name)>0)
            AND (CAST(:day AS date) IS NULL OR c.incorporation_date<:day
                OR (c.incorporation_date=:day AND c.company_key>:key))
        ORDER BY c.incorporation_date DESC, c.company_key LIMIT :limit
    '''), {'report': report_id, 'topic': topic_id, 'query': query, 'day': after_date,
          'key': after_key, 'limit': limit + 1}).mappings().all()
    next_cursor = None
    if len(rows) > limit:
        last = rows[limit - 1]
        next_cursor = base64.urlsafe_b64encode(json.dumps({'binding': binding,
            'date': last['incorporation_date'].isoformat(), 'key': last['company_key']}).encode()).decode().rstrip('=')
    items = [Company(**{key: row[key] for key in ('company_key', 'identifier_type', 'identifier_value',
             'name_en', 'name_zh', 'incorporation_date', 'event_type', 'evidence')},
             registration_date=row['incorporation_date'],
             source={key: row[key] for key in ('resource_id', 'source_url', 'coverage_start',
             'coverage_end_exclusive', 'fetched_at', 'published_date', 'status', 'date_semantics')})
             for row in rows[:limit]]
    return CompaniesResponse(report_id=report_id, population_scope=period_data(report)['population_scope'],
                             items=items, next_cursor=next_cursor)


def read_liquidations(session: Session, limit: int) -> LiquidationsResponse:
    state = session.execute(text("SELECT * FROM company_worker_state WHERE name='liquidations'")).mappings().first()
    if not state or not state['last_success_at']:
        return LiquidationsResponse(data_status='unavailable', items=[],
                                    error_code=state['error_code'] if state else 'not_collected')
    rows = session.execute(text('''SELECT month_start, members_commenced, creditors_commenced,
        members_in_progress, creditors_in_progress, source_url, fetched_at
        FROM company_liquidation_statistics WHERE source_sha256=:sha AND month_start<:current
        ORDER BY month_start DESC LIMIT :limit
    '''), {'sha': state['payload']['sha256'], 'current': today().replace(day=1), 'limit': limit}).mappings().all()
    contiguous = all(left['month_start'] == period_end('month', right['month_start'])
                     for left, right in zip(rows, rows[1:]))
    return LiquidationsResponse(data_status='complete' if rows and contiguous else 'partial',
        items=[dict(row) for row in rows], error_code=state['error_code'], last_success_at=state['last_success_at'])
