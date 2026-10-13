-- Rolling back removes the entire home.tools configuration, including later edits.
DELETE FROM app_settings WHERE key = 'home.tools';
