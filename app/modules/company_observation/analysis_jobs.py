"""Lease fencing, batch resume, durable usage budgets and atomic publication."""
import json
from uuid import uuid4

from sqlalchemy import text

from app.core.config import settings
from app.core.database import get_engine
from app.modules.company_observation.calendar import today
from app.modules.company_observation.storage import ANALYSIS_VERSION


class BudgetExceeded(ValueError):
    def __init__(self, daily: bool):
        self.daily = daily
        super().__init__('budget_exceeded')


def claim_report() -> dict | None:
    if not settings.company_observation_ai_enabled or not settings.deepseek_api_key.get_secret_value():
        return None
    token = str(uuid4())
    with get_engine().begin() as conn:
        conn.execute(text('''UPDATE company_period_reports SET analysis_status='pending'
            WHERE is_current AND data_status='complete' AND observed_company_count>0
            AND analysis_status='not_configured' AND analysis_version=:version
        '''), {'version': ANALYSIS_VERSION})
        row = conn.execute(text('''SELECT * FROM company_period_reports WHERE is_current
            AND data_status='complete' AND observed_company_count>0 AND analysis_version=:version
            AND attempt_count<:max_attempts AND (retry_after IS NULL OR retry_after<now())
            AND (analysis_status IN ('pending', 'failed') OR
                (analysis_status='running' AND lease_until<now()))
            ORDER BY CASE WHEN period_type='month' THEN 0 WHEN period_type='week' THEN 1 ELSE 2 END,
                start_date DESC LIMIT 1 FOR UPDATE SKIP LOCKED
        '''), {'max_attempts': settings.company_observation_max_analysis_attempts,
               'version': ANALYSIS_VERSION}).mappings().first()
        if not row:
            return None
        conn.execute(text('''UPDATE company_period_reports SET analysis_status='running',
            claim_token=:token, lease_until=now()+interval '5 minutes', attempt_count=attempt_count+1,
            error_code=NULL WHERE id=:id
        '''), {'id': row['id'], 'token': token})
    return {**dict(row), 'claim_token': token}


def renew_report(report: dict) -> None:
    with get_engine().begin() as conn:
        count = conn.execute(text('''UPDATE company_period_reports SET lease_until=now()+interval '5 minutes'
            WHERE id=:id AND is_current AND claim_token=:token AND lease_until>now()
                AND analysis_status='running'
        '''), {'id': report['id'], 'token': report['claim_token']}).rowcount
    if not count:
        raise ValueError('analysis_lease_lost')


def report_companies(report: dict) -> list[dict]:
    with get_engine().connect() as conn:
        rows = conn.execute(text('''SELECT c.company_key, r.name_en, r.name_zh
            FROM company_report_companies c JOIN company_source_records r ON r.id=c.source_record_id
            WHERE c.report_id=:id ORDER BY c.company_key
        '''), {'id': report['id']}).mappings().all()
    return [dict(row) for row in rows]


def cached_batch(report: dict, key: str) -> dict | None:
    with get_engine().connect() as conn:
        return conn.execute(text('''SELECT payload FROM company_analysis_batches
            WHERE report_id=:id AND batch_key=:key'''), {'id': report['id'], 'key': key}).scalar()


def save_batch(report: dict, key: str, payload: dict) -> None:
    with get_engine().begin() as conn:
        owner = conn.execute(text('''SELECT id FROM company_period_reports WHERE id=:id
            AND is_current AND claim_token=:token AND lease_until>now() FOR UPDATE
        '''), {'id': report['id'], 'token': report['claim_token']}).first()
        if not owner:
            raise ValueError('analysis_lease_lost')
        conn.execute(text('''INSERT INTO company_analysis_batches(report_id, batch_key, payload)
            VALUES (:id, :key, CAST(:payload AS jsonb)) ON CONFLICT DO NOTHING
        '''), {'id': report['id'], 'key': key, 'payload': json.dumps(payload, ensure_ascii=False)})


def reserve_call(report: dict) -> str:
    usage_id = str(uuid4())
    with get_engine().begin() as conn:
        conn.execute(text('SELECT pg_advisory_xact_lock(72419203)'))
        daily = conn.execute(text('SELECT count(*) FROM company_ai_usage WHERE hk_date=:day'),
                             {'day': today()}).scalar_one()
        total = conn.execute(text('SELECT count(*) FROM company_ai_usage WHERE report_id=:id'),
                             {'id': report['id']}).scalar_one()
        if daily >= settings.company_observation_daily_call_limit:
            raise BudgetExceeded(True)
        if total >= settings.company_observation_report_call_limit:
            raise BudgetExceeded(False)
        conn.execute(text('INSERT INTO company_ai_usage(id, hk_date, report_id) VALUES (:id, :day, :report)'),
                     {'id': usage_id, 'day': today(), 'report': report['id']})
    return usage_id


def finish_call(usage_id: str, tokens: int | None, success: bool) -> None:
    with get_engine().begin() as conn:
        conn.execute(text('''UPDATE company_ai_usage SET status=:status, total_tokens=:tokens WHERE id=:id'''),
                     {'id': usage_id, 'tokens': tokens, 'status': 'completed' if success else 'failed'})


def fail_report(report: dict, code: str, *, budget: bool = False) -> None:
    with get_engine().begin() as conn:
        conn.execute(text('''UPDATE company_period_reports SET analysis_status='failed', error_code=:code,
            lease_until=NULL, claim_token=NULL,
            retry_after=now()+CASE WHEN :budget THEN interval '1 day' ELSE interval '1 hour' END,
            attempt_count=attempt_count-CASE WHEN :budget THEN 1 ELSE 0 END
            WHERE id=:id AND is_current AND claim_token=:token
        '''), {'id': report['id'], 'token': report['claim_token'], 'code': code, 'budget': budget})


def publish(report: dict, summary: dict, topics: list[dict], company_count: int) -> None:
    identified = set().union(*(set(topic['members']) for topic in topics)) if topics else set()
    with get_engine().begin() as conn:
        owner = conn.execute(text('''SELECT id FROM company_period_reports WHERE id=:id
            AND is_current AND claim_token=:token AND lease_until>now()
            AND dataset_fingerprint=:fingerprint AND analysis_status='running' FOR UPDATE
        '''), {'id': report['id'], 'token': report['claim_token'],
              'fingerprint': report['dataset_fingerprint']}).first()
        if not owner:
            raise ValueError('analysis_lease_lost')
        conn.execute(text('DELETE FROM company_topic_memberships WHERE report_id=:id'), {'id': report['id']})
        conn.execute(text('DELETE FROM company_report_topics WHERE report_id=:id'), {'id': report['id']})
        for order, topic in enumerate(topics):
            topic_id = f'topic-{order + 1}'
            conn.execute(text('''INSERT INTO company_report_topics(report_id, topic_id, display,
                rules, company_count, sort_order) VALUES (:id, :topic, CAST(:display AS jsonb),
                    CAST(:rules AS jsonb), :count, :order)
            '''), {'id': report['id'], 'topic': topic_id, 'display': json.dumps(topic['display']),
                  'rules': json.dumps(topic['terms']), 'count': len(topic['members']), 'order': order})
            conn.execute(text('''INSERT INTO company_topic_memberships(report_id, topic_id,
                company_key, evidence) VALUES (:id, :topic, :key, CAST(:evidence AS jsonb))
            '''), [{'id': report['id'], 'topic': topic_id, 'key': key, 'evidence': json.dumps(evidence)}
                  for key, evidence in topic['members'].items()])
        conn.execute(text('''UPDATE company_period_reports SET analysis_status='published',
            summary=CAST(:summary AS jsonb), identified_company_count=:identified,
            unknown_company_count=:unknown, generated_at=now(), model=:model,
            lease_until=NULL, claim_token=NULL, error_code=NULL WHERE id=:id
        '''), {'id': report['id'], 'summary': json.dumps(summary), 'identified': len(identified),
              'unknown': company_count-len(identified), 'model': settings.deepseek_model})
