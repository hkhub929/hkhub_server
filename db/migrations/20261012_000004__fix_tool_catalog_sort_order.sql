-- depends: 20261012_000003__create_grouped_tool_catalog
-- MySQL COALESCE(JSON_EXTRACT(...), 0) in migration 000003 produced string sort orders.
-- Normalize only integer strings; preserve all other configuration and visibility.
UPDATE app_settings AS target
JOIN (
    SELECT
        source.`key`,
        JSON_ARRAYAGG(
            CASE
                WHEN JSON_TYPE(JSON_EXTRACT(source.`value`,
                        CONCAT('$.items[', tool.idx - 1, '].sort_order'))) = 'STRING'
                    AND JSON_UNQUOTE(JSON_EXTRACT(source.`value`,
                        CONCAT('$.items[', tool.idx - 1, '].sort_order'))) REGEXP '^-?[0-9]{1,18}$'
                THEN JSON_SET(
                    JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, ']')),
                    '$.sort_order',
                    CAST(JSON_UNQUOTE(JSON_EXTRACT(source.`value`,
                        CONCAT('$.items[', tool.idx - 1, '].sort_order'))) AS SIGNED)
                )
                ELSE JSON_EXTRACT(source.`value`, CONCAT('$.items[', tool.idx - 1, ']'))
            END
        ) AS items
    FROM app_settings AS source
    JOIN JSON_TABLE(source.`value`, '$.items[*]' COLUMNS (idx FOR ORDINALITY)) AS tool ON TRUE
    WHERE source.`key` = 'home.tools.v2'
    GROUP BY source.`key`
) AS normalized ON normalized.`key` = target.`key`
SET target.`value` = JSON_SET(target.`value`, '$.items', normalized.items)
WHERE target.`key` = 'home.tools.v2';
