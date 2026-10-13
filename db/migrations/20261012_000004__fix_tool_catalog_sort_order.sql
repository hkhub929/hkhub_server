-- depends: 20261012_000003__create_grouped_tool_catalog
-- Normalize only integer strings; preserve all other configuration and visibility.
-- PostgreSQL seed data already uses numeric sort orders; retain this for content edits.
UPDATE app_settings AS target
SET value = jsonb_set(target.value, '{items}', (
    SELECT COALESCE(jsonb_agg(
        CASE
            WHEN jsonb_typeof(tool.item -> 'sort_order') = 'string'
                AND (tool.item ->> 'sort_order') ~ '^-?[0-9]{1,18}$'
            THEN jsonb_set(
                tool.item, '{sort_order}', to_jsonb((tool.item ->> 'sort_order')::bigint)
            )
            ELSE tool.item
        END ORDER BY tool.idx
    ), '[]'::jsonb)
    FROM jsonb_array_elements(target.value -> 'items')
        WITH ORDINALITY AS tool(item, idx)
))
WHERE target.key = 'home.tools.v2';
