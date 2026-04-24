from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/asx_financials",
        alias="DATABASE_URL",
    )
    database_pool_size: int = Field(default=2, alias="DATABASE_POOL_SIZE")
    database_max_overflow: int = Field(default=0, alias="DATABASE_MAX_OVERFLOW")
    database_pool_timeout_seconds: int = Field(
        default=30,
        alias="DATABASE_POOL_TIMEOUT_SECONDS",
    )
    database_pool_recycle_seconds: int = Field(
        default=1800,
        alias="DATABASE_POOL_RECYCLE_SECONDS",
    )
    database_connect_timeout_seconds: int = Field(
        default=10,
        alias="DATABASE_CONNECT_TIMEOUT_SECONDS",
    )
    run_migrations_on_startup: bool = Field(default=False, alias="RUN_MIGRATIONS_ON_STARTUP")
    yahoo_request_timeout_seconds: int = Field(default=30, alias="YAHOO_REQUEST_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
