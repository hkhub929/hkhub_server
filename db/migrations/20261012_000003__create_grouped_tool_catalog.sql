-- depends: 20261012_000002__seed_home_tools
-- Preserve home.tools for older app versions; the grouped app reads home.tools.v2.
-- Edit visible to hide/show a tool. Register feature_id in the native app before publishing.
-- This migration copies existing names, descriptions, visibility and ordering.
INSERT INTO app_settings (`key`, `value`, description)
SELECT
    'home.tools.v2',
    JSON_OBJECT(
        'groups', JSON_ARRAY(
            JSON_OBJECT('id', 'travel', 'sort_order', 10, 'translations', JSON_OBJECT(
                'zh-Hans', JSON_OBJECT('title', '跨境出行'),
                'zh-Hant', JSON_OBJECT('title', '跨境出行'),
                'yue-Hant-HK', JSON_OBJECT('title', '跨境出行'),
                'en', JSON_OBJECT('title', 'Travel')
            )),
            JSON_OBJECT('id', 'residency', 'sort_order', 20, 'translations', JSON_OBJECT(
                'zh-Hans', JSON_OBJECT('title', '身份与居留'),
                'zh-Hant', JSON_OBJECT('title', '身份與居留'),
                'yue-Hant-HK', JSON_OBJECT('title', '身份同居留'),
                'en', JSON_OBJECT('title', 'Residency')
            )),
            JSON_OBJECT('id', 'education', 'sort_order', 30, 'translations', JSON_OBJECT(
                'zh-Hans', JSON_OBJECT('title', '升学'),
                'zh-Hant', JSON_OBJECT('title', '升學'),
                'yue-Hant-HK', JSON_OBJECT('title', '升學'),
                'en', JSON_OBJECT('title', 'Education')
            )),
            JSON_OBJECT('id', 'business', 'sort_order', 40, 'translations', JSON_OBJECT(
                'zh-Hans', JSON_OBJECT('title', '商业'),
                'zh-Hant', JSON_OBJECT('title', '商業'),
                'yue-Hant-HK', JSON_OBJECT('title', '商業'),
                'en', JSON_OBJECT('title', 'Business')
            )),
            JSON_OBJECT('id', 'utilities', 'sort_order', 50, 'translations', JSON_OBJECT(
                'zh-Hans', JSON_OBJECT('title', '实用工具'),
                'zh-Hant', JSON_OBJECT('title', '實用工具'),
                'yue-Hant-HK', JSON_OBJECT('title', '實用工具'),
                'en', JSON_OBJECT('title', 'Utilities')
            ))
        ),
        'items', COALESCE((
            SELECT JSON_ARRAYAGG(JSON_OBJECT(
                'id', JSON_UNQUOTE(JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, '].id'))),
                'feature_id', JSON_UNQUOTE(JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, '].id'))),
                'group_id', CASE JSON_UNQUOTE(JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, '].id')))
                    WHEN 'commute' THEN 'travel'
                    WHEN 'residency' THEN 'residency'
                    WHEN 'education' THEN 'education'
                    WHEN 'business' THEN 'business'
                    ELSE 'utilities'
                END,
                'icon', COALESCE(JSON_UNQUOTE(JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, '].icon'))), 'apps'),
                'visible', COALESCE(JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, '].enabled')), JSON_EXTRACT('true', '$')),
                'sort_order', COALESCE(JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, '].sort_order')), 0),
                'translations', (
                    SELECT JSON_OBJECTAGG(copy.language, JSON_OBJECT(
                        'title', JSON_UNQUOTE(JSON_EXTRACT(
                            source.`value`, CONCAT('$.items[', tool.idx - 1, '].translations."', copy.language, '".title'))),
                        'description', COALESCE(JSON_UNQUOTE(JSON_EXTRACT(
                            source.`value`, CONCAT('$.items[', tool.idx - 1, '].translations."', copy.language, '".description'))), ''),
                        'aliases', JSON_ARRAY()
                    ))
                    FROM JSON_TABLE(
                        JSON_KEYS(JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, '].translations'))),
                        '$[*]' COLUMNS (language VARCHAR(20) PATH '$')
                    ) AS copy
                )
            ))
            FROM JSON_TABLE(source.`value`, '$.items[*]' COLUMNS (idx FOR ORDINALITY)) AS tool
        ), JSON_ARRAY())
    ),
    'Grouped native tool catalog; visible is the only display switch; localized aliases support search'
FROM app_settings AS source
WHERE source.`key` = 'home.tools';
