from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = "sqlite:///./sps-dashboard.db"
    jwt_secret: str = "development-only-change-me"
    jwt_issuer: str = "sps-student-dashboard"
    jwt_audience: str = "sps-browser"
    access_token_minutes: int = 15
    bootstrap_username: str = "bootstrap-admin"
    bootstrap_password: str = "change-this-on-first-run"
    app_encryption_key: str = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
