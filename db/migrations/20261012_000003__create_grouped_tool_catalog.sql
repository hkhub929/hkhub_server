-- depends: 20261012_000002__seed_home_tools
-- Preserve home.tools for older app versions; the grouped app reads home.tools.v2.
-- Edit visible to hide/show a tool. Register feature_id in the native app before publishing.
-- This migration copies existing names, descriptions, visibility and ordering.
INSERT INTO app_settings (key, value, description)
SELECT
    'home.tools.v2',
    jsonb_build_object(
        'groups', jsonb_build_array(
            jsonb_build_object('id', 'travel', 'sort_order', 10, 'translations', jsonb_build_object(
                'zh-Hans', jsonb_build_object('title', '跨境出行'),
                'zh-Hant', jsonb_build_object('title', '跨境出行'),
                'yue-Hant-HK', jsonb_build_object('title', '跨境出行'),
                'en', jsonb_build_object('title', 'Travel')
            )),
            jsonb_build_object('id', 'residency', 'sort_order', 20, 'translations', jsonb_build_object(
                'zh-Hans', jsonb_build_object('title', '身份与居留'),
                'zh-Hant', jsonb_build_object('title', '身份與居留'),
                'yue-Hant-HK', jsonb_build_object('title', '身份同居留'),
                'en', jsonb_build_object('title', 'Residency')
            )),
            jsonb_build_object('id', 'education', 'sort_order', 30, 'translations', jsonb_build_object(
                'zh-Hans', jsonb_build_object('title', '升学'),
                'zh-Hant', jsonb_build_object('title', '升學'),
                'yue-Hant-HK', jsonb_build_object('title', '升學'),
                'en', jsonb_build_object('title', 'Education')
            )),
            jsonb_build_object('id', 'business', 'sort_order', 40, 'translations', jsonb_build_object(
                'zh-Hans', jsonb_build_object('title', '商业'),
                'zh-Hant', jsonb_build_object('title', '商業'),
                'yue-Hant-HK', jsonb_build_object('title', '商業'),
                'en', jsonb_build_object('title', 'Business')
            )),
            jsonb_build_object('id', 'utilities', 'sort_order', 50, 'translations', jsonb_build_object(
                'zh-Hans', jsonb_build_object('title', '实用工具'),
                'zh-Hant', jsonb_build_object('title', '實用工具'),
                'yue-Hant-HK', jsonb_build_object('title', '實用工具'),
                'en', jsonb_build_object('title', 'Utilities')
            ))
        ),
        'items', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                'id', tool.item ->> 'id',
                'feature_id', tool.item ->> 'id',
                'group_id', CASE tool.item ->> 'id'
                    WHEN 'commute' THEN 'travel'
                    WHEN 'residency' THEN 'residency'
                    WHEN 'education' THEN 'education'
                    WHEN 'business' THEN 'business'
                    ELSE 'utilities'
                END,
                'icon', COALESCE(tool.item ->> 'icon', 'apps'),
                'visible', COALESCE(tool.item -> 'enabled', 'true'::jsonb),
                'sort_order', COALESCE(tool.item -> 'sort_order', '0'::jsonb),
                'translations', (
                    SELECT jsonb_object_agg(copy.language, jsonb_build_object(
                        'title', copy.value ->> 'title',
                        'description', COALESCE(copy.value ->> 'description', ''),
                        'aliases', '[]'::jsonb
                    ))
                    FROM jsonb_each(tool.item -> 'translations') AS copy(language, value)
                )
            ) ORDER BY tool.idx)
            FROM jsonb_array_elements(source.value -> 'items')
                WITH ORDINALITY AS tool(item, idx)
        ), '[]'::jsonb)
    ),
    'Grouped native tool catalog; visible is the only display switch; localized aliases support search'
FROM app_settings AS source
WHERE source.key = 'home.tools';
