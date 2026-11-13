from functools import lru_cache
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    app_build_sha: str = "unknown"
    database_url: str = "sqlite:///./sps-dashboard.db"
    jwt_secret: str = "development-only-change-me"
    jwt_issuer: str = "sps-student-dashboard"
    jwt_audience: str = "sps-browser"
    access_token_minutes: int = 15
    bootstrap_username: str = "bootstrap-admin"
    bootstrap_password: str = "change-this-on-first-run"
    app_encryption_key: str = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="
    app_encryption_previous_keys: str = ""
    student_import_retention_days: int = Field(default=0, ge=0, le=3650)
    legacy_pri_key_hex: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore", hide_input_in_errors=True)

    @model_validator(mode="after")
    def validate_production_configuration(self) -> "Settings":
        if self.app_env.strip().lower() != "production":
            return self

        problems = []
        database_url = urlsplit(self.database_url)
        if database_url.scheme.lower() != "postgresql+psycopg" or not database_url.hostname or database_url.path in ("", "/"):
            problems.append("DATABASE_URL must use PostgreSQL with psycopg")
        if len(self.jwt_secret) < 32:
            problems.append("JWT_SECRET must be a non-default secret of at least 32 characters")
        if len(self.bootstrap_password) < 32:
            problems.append("BOOTSTRAP_PASSWORD must be a non-default secret of at least 32 characters")

        encryption_keys = [self.app_encryption_key.strip(), *(key.strip() for key in self.app_encryption_previous_keys.split(","))]
        if not encryption_keys[0]:
            problems.append("APP_ENCRYPTION_KEY is required")
        if encryption_keys[0] == "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=":
            problems.append("APP_ENCRYPTION_KEY must not use the development key")
        configured_keys = [key for key in encryption_keys if key]
        if len(configured_keys) != len(set(configured_keys)):
            problems.append("Application encryption keys must be unique")
        for key in configured_keys:
            try:
                Fernet(key.encode())
            except (ValueError, TypeError):
                problems.append("Application encryption key configuration is invalid")
                break

        if self.legacy_pri_key_hex.strip():
            try:
                legacy_key = bytes.fromhex(self.legacy_pri_key_hex)
                if len(legacy_key) not in (16, 24, 32):
                    raise ValueError
            except ValueError:
                problems.append("LEGACY_PRI_KEY_HEX must be a valid 16, 24 or 32 byte hexadecimal key")

        if problems:
            raise ValueError("Invalid production configuration: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
