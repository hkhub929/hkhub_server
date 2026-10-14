-- depends: 20261013_000008__update_commute_tool_copy
-- Reframe the residency entry around recording the seven-year journey. The
-- title, sort order, visibility and feature_id are all preserved; only the
-- description changes, per language.
UPDATE app_settings AS target
SET value = jsonb_set(target.value, '{items}', (
    SELECT COALESCE(jsonb_agg(
        CASE WHEN tool.item ->> 'id' = 'residency' THEN
            jsonb_set(tool.item, '{translations}', (
                SELECT jsonb_object_agg(copy.language,
                    jsonb_set(copy.value, '{description}', to_jsonb(
                        CASE copy.language
                            WHEN 'en' THEN
                                'Track your stay and the seven-year journey'::text
                            WHEN 'zh-Hans' THEN
                                '记录留港日子，见证七年历程'::text
                            WHEN 'yue-Hant-HK' THEN
                                '記低留港日子，見證七年歷程'::text
                            ELSE '記錄留港日子，見證七年歷程'::text
                        END
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
