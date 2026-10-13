-- depends: 20261012_000006__shorten_home_tool_titles
-- One independently collected resident/visitor snapshot per Hong Kong 15-minute slot.
CREATE TABLE commute_observations (
    audience TEXT NOT NULL CHECK (audience IN ('resident', 'visitor')),
    hk_date DATE NOT NULL,
    hk_slot SMALLINT NOT NULL CHECK (hk_slot BETWEEN 0 AND 95),
    attempted_at TIMESTAMPTZ NOT NULL,
    attempt_count SMALLINT NOT NULL DEFAULT 1 CHECK (attempt_count BETWEEN 1 AND 3),
    fetched_at TIMESTAMPTZ,
    payload JSONB,
    error_code TEXT,
    PRIMARY KEY (audience, hk_date, hk_slot),
    CHECK (
        (payload IS NOT NULL AND jsonb_typeof(payload) = 'object'
            AND fetched_at IS NOT NULL AND error_code IS NULL)
        OR (payload IS NULL AND fetched_at IS NULL AND error_code IS NOT NULL)
    )
);
CREATE INDEX commute_observations_recent_idx
    ON commute_observations (audience, attempted_at DESC);
