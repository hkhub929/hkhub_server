import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import text

from app.core.database import get_engine
from app.modules.rent.catalog import PARSER_VERSION

LOCKS = {'rental_index': 72419301, 'average_rent': 72419302}


def claim(source_id: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    with get_engine().begin() as connection:
        if not connection.execute(text('SELECT pg_try_advisory_xact_lock(:key)'),
                                  {'key': LOCKS[source_id]}).scalar():
            return None
        state = connection.execute(text('SELECT * FROM rent_source_state WHERE source_id=:source FOR UPDATE'),
                                   {'source': source_id}).mappings().one()
        elapsed = (now - state['last_attempt_at']).total_seconds() if state['last_attempt_at'] else 86400
        status, count = state['last_attempt_status'], state['attempt_count']
        wait = 1800 if status == 'fetching' else 300 if status == 'failed' and count < 3 else 86400
        if elapsed < wait:
            return None
        count = 1 if elapsed >= 86400 else min(3, count + 1)
        connection.execute(text('''
            UPDATE rent_source_state SET last_attempt_at=:now, last_attempt_status='fetching',
                attempt_count=:count, last_error_code=NULL WHERE source_id=:source
        '''), {'now': now, 'count': count, 'source': source_id})
    return now


def fail(source_id: str, attempt: datetime, code: str) -> None:
    with get_engine().begin() as connection:
        connection.execute(text('''
            UPDATE rent_source_state SET last_attempt_status='failed', last_error_code=:code
            WHERE source_id=:source AND last_attempt_at=:attempt
        '''), {'source': source_id, 'attempt': attempt, 'code': code})


def publish(source_id: str, attempt: datetime, payload: dict) -> None:
    now = datetime.now(timezone.utc)
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    with get_engine().begin() as connection:
        state = connection.execute(text('SELECT * FROM rent_source_state WHERE source_id=:source FOR UPDATE'),
                                   {'source': source_id}).mappings().one()
        if state['last_attempt_at'] != attempt:
            return  # A newer collector owns the lease; never publish an older download.
        if state['active_snapshot_id']:
            previous = connection.execute(text('SELECT series_data FROM rent_snapshots WHERE id=:id'),
                                          {'id': state['active_snapshot_id']}).scalar_one()
            for identity, points in previous.items():
                new_months = {point['month'] for point in payload['series_data'].get(identity, [])}
                if not {point['month'] for point in points}.issubset(new_months):
                    raise ValueError('Source history was truncated')
        identity = connection.execute(text('''
            INSERT INTO rent_snapshots (id, source_id, content_hash, parser_version, accepted_at,
                coverage_start_month, coverage_end_month, catalog, series_data)
            VALUES (:id, :source, :hash, :parser, :now, :start, :end,
                    CAST(:catalog AS jsonb), CAST(:data AS jsonb))
            ON CONFLICT (source_id, content_hash, parser_version) DO UPDATE
                SET content_hash=EXCLUDED.content_hash RETURNING id
        '''), {'id': uuid4(), 'source': source_id, 'hash': digest, 'parser': PARSER_VERSION,
              'now': now, 'start': payload['coverage_start_month'], 'end': payload['coverage_end_month'],
              'catalog': json.dumps(payload['catalog']), 'data': json.dumps(payload['series_data'])}).scalar_one()
        connection.execute(text('''
            UPDATE rent_source_state SET active_snapshot_id=:id, last_checked_at=:now,
                last_changed_at=CASE WHEN active_snapshot_id IS DISTINCT FROM :id THEN :now
                                     ELSE last_changed_at END,
                last_attempt_status='success', last_error_code=NULL, attempt_count=0
            WHERE source_id=:source
        '''), {'id': identity, 'now': now, 'source': source_id})
        # Bounded revision retention: current snapshot plus up to eleven prior revisions.
        connection.execute(text('''
            DELETE FROM rent_snapshots WHERE source_id=:source AND id<>:active AND id NOT IN (
                SELECT id FROM rent_snapshots WHERE source_id=:source
                ORDER BY accepted_at DESC LIMIT 11
            )
        '''), {'source': source_id, 'active': identity})
