-- Removes the grouped catalog and later edits; the legacy home.tools configuration is preserved.
DELETE FROM app_settings WHERE key = 'home.tools.v2';
