-- Dropped configuration may contain operator edits; never pretend an empty table restores it.
DO $$
BEGIN
    RAISE EXCEPTION 'Home tool settings removal is irreversible; restore app_settings and its trigger function from a database backup before reverting this migration';
END;
$$;
