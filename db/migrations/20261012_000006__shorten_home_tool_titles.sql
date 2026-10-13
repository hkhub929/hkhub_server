-- depends: 20261012_000005__simplify_tool_catalog_groups
-- Short labels for the fixed three-column grid; preserve descriptions and other metadata.
UPDATE app_settings AS target
SET value = jsonb_set(target.value, '{items}', (
    SELECT COALESCE(jsonb_agg(
        CASE WHEN tool.item ->> 'id' IN ('commute', 'residency') THEN
            jsonb_set(tool.item, '{translations}', (
                SELECT jsonb_object_agg(copy.language,
                    CASE WHEN copy.language IN ('zh-Hans', 'zh-Hant', 'yue-Hant-HK', 'en') THEN
                        jsonb_set(copy.value, '{title}', to_jsonb(
                            CASE
                                WHEN tool.item ->> 'id' = 'commute' THEN
                                    CASE WHEN copy.language = 'en'
                                        THEN 'HK-Shenzhen commute'::text ELSE '港深通勤'::text END
                                WHEN copy.language = 'en' THEN 'Residency planning'::text
                                WHEN copy.language = 'zh-Hans' THEN '永居规划'::text
                                ELSE '永居規劃'::text
                            END
                        ))
                    ELSE copy.value END
                )
                FROM jsonb_each(tool.item -> 'translations') AS copy(language, value)
            ))
        ELSE tool.item END ORDER BY tool.idx
    ), '[]'::jsonb)
    FROM jsonb_array_elements(target.value -> 'items')
        WITH ORDINALITY AS tool(item, idx)
))
WHERE target.key = 'home.tools.v2';
