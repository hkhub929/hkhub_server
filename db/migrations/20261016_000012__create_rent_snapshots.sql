-- depends: 20261016_000011__create_company_observation
CREATE TABLE rent_snapshots (
    id UUID PRIMARY KEY,
    source_id TEXT NOT NULL CHECK (source_id IN ('rental_index', 'average_rent')),
    content_hash TEXT NOT NULL,
    parser_version TEXT NOT NULL,
    accepted_at TIMESTAMPTZ NOT NULL,
    source_updated_at TIMESTAMPTZ,
    coverage_start_month TEXT NOT NULL CHECK (coverage_start_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    coverage_end_month TEXT NOT NULL CHECK (coverage_end_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'),
    catalog JSONB NOT NULL CHECK (jsonb_typeof(catalog) = 'array'),
    series_data JSONB NOT NULL CHECK (jsonb_typeof(series_data) = 'object'),
    UNIQUE (source_id, content_hash, parser_version),
    UNIQUE (source_id, id),
    CHECK (coverage_start_month <= coverage_end_month)
);
CREATE INDEX rent_snapshots_source_recent_idx ON rent_snapshots (source_id, accepted_at DESC);

CREATE TABLE rent_source_state (
    source_id TEXT PRIMARY KEY CHECK (source_id IN ('rental_index', 'average_rent')),
    active_snapshot_id UUID,
    last_attempt_at TIMESTAMPTZ,
    last_checked_at TIMESTAMPTZ,
    last_changed_at TIMESTAMPTZ,
    last_attempt_status TEXT NOT NULL DEFAULT 'not_collected'
        CHECK (last_attempt_status IN ('not_collected', 'fetching', 'success', 'failed')),
    last_error_code TEXT,
    attempt_count SMALLINT NOT NULL DEFAULT 0 CHECK (attempt_count BETWEEN 0 AND 3),
    FOREIGN KEY (source_id, active_snapshot_id) REFERENCES rent_snapshots (source_id, id)
);
INSERT INTO rent_source_state (source_id) VALUES ('rental_index'), ('average_rent');
