from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Environment configuration shared by the API and migration commands."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "HK Hub API"
    version: str = "0.1.0"
    environment: Literal["local", "test", "production"] = "local"
    api_prefix: str = "/api"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    database_url: SecretStr = SecretStr("")
    postgres_bin_dir: str = ""
    cors_origins: list[str] = ["http://localhost:8080", "http://127.0.0.1:8080"]
    database_pool_size: int = 5
    database_max_overflow: int = 10
    upstream_timeout_seconds: float = 15.0
    # Cross-border commute sampling. Retention must comfortably exceed the history
    # window so a full week of comparison survives weekends and public holidays.
    commute_collect_interval_minutes: int = 15
    commute_history_days: int = 7
    commute_retention_days: int = 30
    commute_stale_after_minutes: int = 30
    deepseek_api_key: SecretStr = SecretStr("")
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    deepseek_timeout_seconds: float = 150.0

    @field_validator("deepseek_base_url")
    @classmethod
    def validate_deepseek_url(cls, value: str) -> str:
        uri = urlsplit(value)
        if (uri.scheme != "https" or not uri.hostname or uri.username
                or uri.password or uri.query or uri.fragment):
            raise ValueError("DEEPSEEK_BASE_URL must be an HTTPS URL without credentials")
        return value.rstrip("/")

    @field_validator("deepseek_timeout_seconds")
    @classmethod
    def validate_deepseek_timeout(cls, value: float) -> float:
        if not 10 <= value <= 180:
            raise ValueError("DEEPSEEK_TIMEOUT_SECONDS must be between 10 and 180")
        return value

    @field_validator("commute_collect_interval_minutes")
    @classmethod
    def validate_commute_interval(cls, value: int) -> int:
        # The official source publishes every 15 minutes; a faster loop only repeats it.
        if not 5 <= value <= 60:
            raise ValueError("COMMUTE_COLLECT_INTERVAL_MINUTES must be between 5 and 60")
        return value

    @field_validator("commute_history_days")
    @classmethod
    def validate_commute_history_days(cls, value: int) -> int:
        if not 1 <= value <= 14:
            raise ValueError("COMMUTE_HISTORY_DAYS must be between 1 and 14")
        return value

    @field_validator("commute_retention_days")
    @classmethod
    def validate_commute_retention_days(cls, value: int) -> int:
        if not 8 <= value <= 365:
            raise ValueError("COMMUTE_RETENTION_DAYS must be between 8 and 365")
        return value

    @field_validator("commute_stale_after_minutes")
    @classmethod
    def validate_commute_stale_after(cls, value: int) -> int:
        # Two missed sampling windows are treated as stale rather than current.
        if not 15 <= value <= 240:
            raise ValueError("COMMUTE_STALE_AFTER_MINUTES must be between 15 and 240")
        return value

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("API_PREFIX must start with '/' and must not end with '/'")
        return value


settings = Settings()
