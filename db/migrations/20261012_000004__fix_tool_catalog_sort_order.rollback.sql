-- Intentional no-op: normalized integers are valid for both versions of the catalog schema.
-- Rolling back must not reintroduce invalid strings or discard subsequent configuration edits.
SELECT 1;
