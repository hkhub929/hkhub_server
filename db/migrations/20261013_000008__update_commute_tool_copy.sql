-- depends: 20261013_000007__create_commute_observations
-- Keep the legacy home.tools actions inactive for older apps without a commute route.
-- The grouped app executes only its compiled feature_id whitelist.
UPDATE app_settings AS target
SET value = jsonb_set(target.value, '{items}', (
    SELECT COALESCE(jsonb_agg(
        CASE WHEN tool.item ->> 'feature_id' = 'commute' THEN
            jsonb_set(tool.item, '{translations}', (
                SELECT jsonb_object_agg(copy.language,
                    jsonb_set(copy.value, '{description}', to_jsonb(
                        CASE WHEN copy.language = 'en' THEN
                            'Hong Kong immigration queues, seven-day reference and connections'::text
                        WHEN copy.language = 'zh-Hans' THEN
                            '港方入境轮候、七天同时段参考与香港侧接驳'::text
                        ELSE '港方入境輪候、七天同時段參考與香港側接駁'::text END
                    ))
                )
                FROM jsonb_each(tool.item -> 'translations') AS copy(language, value)
            ))
        ELSE tool.item END ORDER BY tool.idx
    ), '[]'::jsonb)
    FROM jsonb_array_elements(target.value -> 'items')
        WITH ORDINALITY AS tool(item, idx)
))
WHERE target.key = 'home.tools.v2';
