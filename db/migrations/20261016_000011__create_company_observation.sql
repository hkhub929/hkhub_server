-- depends: 20261016_000010__drop_home_tool_settings
CREATE TABLE company_source_files (
    id uuid PRIMARY KEY,
    resource_id text NOT NULL,
    source_url text NOT NULL,
    coverage_start date NOT NULL,
    coverage_end_exclusive date NOT NULL,
    content_sha256 text NOT NULL,
    raw_content bytea NOT NULL,
    parser_version text NOT NULL,
    fetched_at timestamptz NOT NULL DEFAULT now(),
    published_date date,
    status text NOT NULL CHECK (status IN ('complete', 'partial', 'invalid')),
    diagnostics jsonb NOT NULL,
    UNIQUE (resource_id, content_sha256, parser_version),
    CHECK (coverage_end_exclusive > coverage_start)
);
CREATE INDEX company_source_coverage ON company_source_files (coverage_start, fetched_at DESC);

CREATE TABLE company_source_records (
    id bigserial PRIMARY KEY,
    source_file_id uuid NOT NULL REFERENCES company_source_files(id),
    row_locator integer NOT NULL,
    company_key text,
    identifier_type text,
    identifier_value text,
    name_en text NOT NULL,
    name_zh text NOT NULL,
    incorporation_date date,
    event_type text NOT NULL,
    error_code text,
    UNIQUE (source_file_id, row_locator)
);
CREATE INDEX company_records_source_date ON company_source_records (source_file_id, incorporation_date);

CREATE TABLE company_period_reports (
    id uuid PRIMARY KEY,
    period_type text NOT NULL CHECK (period_type IN ('week', 'month', 'year')),
    start_date date NOT NULL,
    end_date_exclusive date NOT NULL,
    dataset_fingerprint text NOT NULL,
    analysis_version text NOT NULL,
    data_status text NOT NULL CHECK (data_status IN ('complete', 'partial', 'unavailable')),
    analysis_status text NOT NULL CHECK (analysis_status IN
        ('pending', 'running', 'published', 'failed', 'not_configured', 'not_needed', 'superseded')),
    is_current boolean NOT NULL DEFAULT true,
    observed_company_count integer NOT NULL CHECK (observed_company_count >= 0),
    sources jsonb NOT NULL,
    missing_resources jsonb NOT NULL,
    summary jsonb,
    identified_company_count integer,
    unknown_company_count integer,
    error_code text,
    claim_token uuid,
    lease_until timestamptz,
    attempt_count integer NOT NULL DEFAULT 0,
    retry_after timestamptz,
    model text,
    generated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (period_type, start_date, dataset_fingerprint, analysis_version),
    CHECK (end_date_exclusive > start_date)
);
CREATE UNIQUE INDEX company_current_period ON company_period_reports (period_type, start_date) WHERE is_current;
CREATE INDEX company_analysis_queue ON company_period_reports (analysis_status, start_date DESC) WHERE is_current;

CREATE TABLE company_report_companies (
    report_id uuid NOT NULL REFERENCES company_period_reports(id),
    company_key text NOT NULL,
    source_record_id bigint NOT NULL REFERENCES company_source_records(id),
    incorporation_date date NOT NULL,
    search_name text NOT NULL,
    PRIMARY KEY (report_id, company_key)
);
CREATE INDEX company_list_cursor ON company_report_companies (report_id, incorporation_date DESC, company_key);

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

CREATE TABLE company_liquidation_statistics (
    source_sha256 text NOT NULL,
    month_start date NOT NULL,
    members_commenced integer NOT NULL CHECK (members_commenced >= 0),
    creditors_commenced integer NOT NULL CHECK (creditors_commenced >= 0),
    members_in_progress integer NOT NULL CHECK (members_in_progress >= 0),
    creditors_in_progress integer NOT NULL CHECK (creditors_in_progress >= 0),
    source_url text NOT NULL,
    fetched_at timestamptz NOT NULL,
    PRIMARY KEY (source_sha256, month_start)
);
CREATE TABLE company_worker_state (
    name text PRIMARY KEY,
    claim_token uuid,
    lease_until timestamptz,
    last_success_at timestamptz,
    last_attempt_at timestamptz,
    error_code text,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb
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
