-- Initial platform configuration for PostgreSQL.
-- Business tables are added by later migrations.
-- Never edit an applied migration; create a new versioned SQL file instead.
-- Timestamps preserve UTC instants; application connections use UTC.
CREATE TABLE app_settings (
    key VARCHAR(128) PRIMARY KEY,
    value JSONB NOT NULL,
    description VARCHAR(512) NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ(6) NOT NULL DEFAULT CURRENT_TIMESTAMP
);

COMMENT ON TABLE app_settings IS
    'Non-secret application configuration; credentials stay in environment variables';

CREATE FUNCTION set_app_settings_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF NEW IS DISTINCT FROM OLD THEN
        NEW.updated_at = statement_timestamp();
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER app_settings_updated_at
BEFORE UPDATE ON app_settings
FOR EACH ROW EXECUTE FUNCTION set_app_settings_updated_at();
