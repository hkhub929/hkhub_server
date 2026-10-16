-- depends: 20261016_000012__create_rent_snapshots
CREATE TABLE company_report_topics (
    report_id uuid NOT NULL REFERENCES company_period_reports(id),
    topic_id text NOT NULL,
    display jsonb NOT NULL,
    rules jsonb NOT NULL,
    company_count integer NOT NULL CHECK (company_count > 0),
    sort_order integer NOT NULL,
    PRIMARY KEY (report_id, topic_id)
);
CREATE TABLE company_topic_memberships (
    report_id uuid NOT NULL,
    topic_id text NOT NULL,
    company_key text NOT NULL,
    evidence jsonb NOT NULL,
    PRIMARY KEY (report_id, topic_id, company_key),
    FOREIGN KEY (report_id, topic_id) REFERENCES company_report_topics(report_id, topic_id),
    FOREIGN KEY (report_id, company_key) REFERENCES company_report_companies(report_id, company_key)
);
CREATE TABLE company_analysis_batches (
    report_id uuid NOT NULL REFERENCES company_period_reports(id),
    batch_key text NOT NULL,
    payload jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (report_id, batch_key)
);
CREATE TABLE company_ai_usage (
    id uuid PRIMARY KEY,
    hk_date date NOT NULL,
    report_id uuid NOT NULL REFERENCES company_period_reports(id),
    status text NOT NULL DEFAULT 'reserved',
    total_tokens integer,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX company_ai_daily_usage ON company_ai_usage (hk_date);
CREATE INDEX company_analysis_queue ON company_period_reports (analysis_status, start_date DESC) WHERE is_current;

UPDATE company_period_reports SET analysis_status='not_configured'
WHERE is_current AND analysis_status='not_needed';
