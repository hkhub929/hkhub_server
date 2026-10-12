-- depends: 20261012_000004__fix_tool_catalog_sort_order
-- Use two categories. Only business data belongs to utilities.
-- Preserve tool names, translations, sort orders, feature IDs and visibility.
UPDATE app_settings AS target
LEFT JOIN (
    SELECT
        source.`key`,
        JSON_ARRAYAGG(JSON_SET(
            JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, ']')),
            '$.group_id',
            CASE JSON_UNQUOTE(JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, '].id')))
                WHEN 'business' THEN 'utilities'
                ELSE 'new_hongkongers'
            END
        )) AS items
    FROM app_settings AS source
    JOIN JSON_TABLE(source.`value`, '$.items[*]' COLUMNS (idx FOR ORDINALITY)) AS tool ON TRUE
    WHERE source.`key` = 'home.tools.v2'
    GROUP BY source.`key`
) AS regrouped ON regrouped.`key` = target.`key`
SET target.`value` = JSON_SET(
    target.`value`,
    '$.groups', JSON_ARRAY(
        JSON_OBJECT(
            'id', 'new_hongkongers', 'sort_order', 10,
            'translations', JSON_OBJECT(
                'zh-Hans', JSON_OBJECT('title', '新港人'),
                'zh-Hant', JSON_OBJECT('title', '新港人'),
                'yue-Hant-HK', JSON_OBJECT('title', '新港人'),
                'en', JSON_OBJECT('title', 'New Hongkongers')
            )
        ),
        JSON_OBJECT(
            'id', 'utilities', 'sort_order', 20,
            'translations', JSON_OBJECT(
                'zh-Hans', JSON_OBJECT('title', '实用工具'),
                'zh-Hant', JSON_OBJECT('title', '實用工具'),
                'yue-Hant-HK', JSON_OBJECT('title', '實用工具'),
                'en', JSON_OBJECT('title', 'Utilities')
            )
        )
    ),
    '$.items', IF(regrouped.items IS NULL, JSON_ARRAY(), regrouped.items)
)
WHERE target.`key` = 'home.tools.v2';
