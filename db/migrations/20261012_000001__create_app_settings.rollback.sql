-- Explicit rollback: application configuration values will be removed.
DROP TABLE app_settings;
DROP FUNCTION set_app_settings_updated_at();
