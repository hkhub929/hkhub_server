-- Initial platform configuration for MySQL 8.
-- Business tables are added by later migrations.
-- Never edit an applied migration; create a new versioned SQL file instead.
-- Application connections use UTC for all date/time values.
CREATE TABLE app_settings (
    `key` VARCHAR(128) NOT NULL,
    `value` JSON NOT NULL,
    description VARCHAR(512) NOT NULL DEFAULT '',
    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
    COMMENT='Non-secret application configuration; credentials stay in environment variables';
