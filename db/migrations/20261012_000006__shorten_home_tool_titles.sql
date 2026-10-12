-- depends: 20261012_000005__simplify_tool_catalog_groups
-- Short labels for the fixed three-column grid; preserve descriptions and other metadata.
UPDATE app_settings AS target
JOIN (
    SELECT
        source.`key`,
        JSON_ARRAYAGG(
            CASE JSON_UNQUOTE(JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, '].id')))
                WHEN 'commute' THEN JSON_SET(
                    JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, ']')),
                    '$.translations."zh-Hans".title', '港深通勤',
                    '$.translations."zh-Hant".title', '港深通勤',
                    '$.translations."yue-Hant-HK".title', '港深通勤',
                    '$.translations."en".title', 'HK-Shenzhen commute'
                )
                WHEN 'residency' THEN JSON_SET(
                    JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, ']')),
                    '$.translations."zh-Hans".title', '永居规划',
                    '$.translations."zh-Hant".title', '永居規劃',
                    '$.translations."yue-Hant-HK".title', '永居規劃',
                    '$.translations."en".title', 'Residency planning'
                )
                ELSE JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, ']'))
            END
        ) AS items
    FROM app_settings AS source
    JOIN JSON_TABLE(source.`value`, '$.items[*]' COLUMNS (idx FOR ORDINALITY)) AS tool ON TRUE
    WHERE source.`key` = 'home.tools.v2'
    GROUP BY source.`key`
) AS renamed ON renamed.`key` = target.`key`
SET target.`value` = JSON_SET(target.`value`, '$.items', renamed.items)
WHERE target.`key` = 'home.tools.v2';
