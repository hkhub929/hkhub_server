-- depends: 20261016_000012__create_rent_snapshots
-- Remove the AI trend analysis: drop its tables and reset report states.
DROP TABLE company_topic_memberships;
DROP TABLE company_report_topics;
DROP TABLE company_analysis_batches;
DROP TABLE company_ai_usage;
DROP INDEX IF EXISTS company_analysis_queue;

UPDATE company_period_reports SET analysis_status='not_needed',
    summary=NULL, identified_company_count=NULL, unknown_company_count=NULL,
    attempt_count=0, retry_after=NULL, claim_token=NULL, lease_until=NULL,
    error_code=NULL, model=NULL, generated_at=NULL
WHERE analysis_status IN ('pending', 'running', 'published', 'failed', 'not_configured');
