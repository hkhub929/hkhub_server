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
    local_database_autostart: bool = True
    local_database_admin_url: SecretStr = SecretStr("")
    mysqld_bin: str = ""
    cors_origins: list[str] = ["http://localhost:8080", "http://127.0.0.1:8080"]
    database_pool_size: int = 5
    database_max_overflow: int = 10
    upstream_timeout_seconds: float = 15.0
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

    @field_validator("api_prefix")
    @classmethod
    def validate_api_prefix(cls, value: str) -> str:
        if not value.startswith("/") or value.endswith("/"):
            raise ValueError("API_PREFIX must start with '/' and must not end with '/'")
        return value


settings = Settings()
