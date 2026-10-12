from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables / .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "HK Hub API"
    version: str = "0.1.0"
    api_prefix: str = "/api"
    debug: bool = False
    database_url: str = ""


settings = Settings()
