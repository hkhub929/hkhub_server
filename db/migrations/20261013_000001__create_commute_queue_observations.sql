-- depends: 20261012_000006__shorten_home_tool_titles
-- One row per control point, audience, direction and Hong Kong local 15-minute window.
-- Written only by the commute collector (app/modules/commute/collector.py); the API
-- reads the latest row per window. The official source reports a coarse status code,
-- never passenger counts, so no derived column stores a computed index.
CREATE TABLE commute_queue_observations (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    port_code TEXT NOT NULL,
    audience TEXT NOT NULL,
    direction TEXT NOT NULL,
    status_code SMALLINT NOT NULL,
    hk_date DATE NOT NULL,
    hk_slot SMALLINT NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    source TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT commute_queue_observations_audience_check
        CHECK (audience IN ('resident', 'visitor')),
    CONSTRAINT commute_queue_observations_direction_check
        CHECK (direction IN ('arrival', 'departure')),
    CONSTRAINT commute_queue_observations_slot_check
        CHECK (hk_slot BETWEEN 0 AND 95),
    -- Duplicate samples in one window are ignored, so the first sample is kept.
    CONSTRAINT commute_queue_observations_window_key
        UNIQUE (port_code, audience, direction, hk_date, hk_slot)
);

COMMENT ON TABLE commute_queue_observations IS
    'Immigration Department land boundary queue status sampled every 15 minutes; status_code is not a passenger count';
COMMENT ON COLUMN commute_queue_observations.hk_slot IS
    'Index of the Hong Kong local 15-minute window, counted from local midnight';
COMMENT ON COLUMN commute_queue_observations.observed_at IS
    'UTC instant the upstream response was received, never the official assessment time';

-- Window comparison leads with the unique key; retention deletes by date alone.
CREATE INDEX commute_queue_observations_hk_date_idx
    ON commute_queue_observations (hk_date);
