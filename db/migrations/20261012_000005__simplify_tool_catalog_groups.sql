-- depends: 20261012_000004__fix_tool_catalog_sort_order
-- Use two categories. Only business data belongs to utilities.
-- Preserve tool names, translations, sort orders, feature IDs and visibility.
UPDATE app_settings AS target
SET value = jsonb_set(
    jsonb_set(target.value, '{groups}', jsonb_build_array(
        jsonb_build_object(
            'id', 'new_hongkongers', 'sort_order', 10,
            'translations', jsonb_build_object(
                'zh-Hans', jsonb_build_object('title', '新港人'),
                'zh-Hant', jsonb_build_object('title', '新港人'),
                'yue-Hant-HK', jsonb_build_object('title', '新港人'),
                'en', jsonb_build_object('title', 'New Hongkongers')
            )
        ),
        jsonb_build_object(
            'id', 'utilities', 'sort_order', 20,
            'translations', jsonb_build_object(
                'zh-Hans', jsonb_build_object('title', '实用工具'),
                'zh-Hant', jsonb_build_object('title', '實用工具'),
                'yue-Hant-HK', jsonb_build_object('title', '實用工具'),
                'en', jsonb_build_object('title', 'Utilities')
            )
        )
    )),
    '{items}', (
        SELECT COALESCE(jsonb_agg(jsonb_set(
            tool.item, '{group_id}', to_jsonb(CASE tool.item ->> 'id'
                WHEN 'business' THEN 'utilities'::text
                ELSE 'new_hongkongers'::text
            END)
        ) ORDER BY tool.idx), '[]'::jsonb)
        FROM jsonb_array_elements(target.value -> 'items')
            WITH ORDINALITY AS tool(item, idx)
    )
)
WHERE target.key = 'home.tools.v2';
