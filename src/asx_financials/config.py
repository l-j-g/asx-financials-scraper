from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = Field(default="development", alias="APP_ENV")
    mongodb_uri: str = Field(
        default="mongodb://localhost:27017",
        alias="MONGODB_URI",
    )
    mongodb_database: str = Field(
        default="asx_financials",
        alias="MONGODB_DATABASE",
    )
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
