-- depends: 20261014_000009__update_residency_tool_copy
-- Home tools now ship with the app. Upgrade clients before removing the legacy API.
-- Back up app_settings before applying: its configuration cannot be reconstructed on rollback.
-- Refuse to discard unrelated settings if this table gained another consumer.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM app_settings WHERE key NOT IN ('home.tools', 'home.tools.v2')
    ) THEN
        RAISE EXCEPTION 'app_settings contains unrelated settings; migrate them before dropping the table';
    END IF;
END;
$$;

-- Dropping the table also removes its app_settings_updated_at trigger.
DROP TABLE app_settings;
DROP FUNCTION set_app_settings_updated_at();
