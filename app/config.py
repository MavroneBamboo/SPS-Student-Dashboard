from functools import lru_cache
from urllib.parse import unquote, urlsplit

from cryptography.fernet import Fernet
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = Field(default="sqlite:///./sps-dashboard.db", repr=False)
    jwt_secret: str = Field(default="development-only-change-me", repr=False)
    jwt_issuer: str = "sps-student-dashboard"
    jwt_audience: str = "sps-browser"
    access_token_minutes: int = Field(default=15, ge=1, le=60)
    bootstrap_username: str = "bootstrap-admin"
    bootstrap_password: str = Field(default="change-this-on-first-run", repr=False)
    app_encryption_key: str = Field(default="MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA=", repr=False)
    app_encryption_previous_keys: str = Field(default="", repr=False)
    student_import_retention_days: int = Field(default=0, ge=0, le=3650)
    legacy_pri_key_hex: str = Field(default="", repr=False)

    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    @model_validator(mode="after")
    def require_safe_deployment_configuration(self):
        environment = self.app_env.strip().lower()
        if environment not in {"staging", "production", "prod"}:
            return self

        errors = []
        placeholder_prefixes = ("change-this", "development-only", "ci-only", "test-secret", "test-bootstrap")
        jwt_secret = self.jwt_secret.strip()
        bootstrap_password = self.bootstrap_password.strip()
        jwt_is_placeholder = jwt_secret.lower().startswith(placeholder_prefixes)
        bootstrap_is_placeholder = bootstrap_password.lower().startswith(placeholder_prefixes)
        if len(jwt_secret.encode("utf-8")) < 32 or jwt_is_placeholder or jwt_secret != self.jwt_secret:
            errors.append("JWT_SECRET must be a unique secret of at least 32 bytes")
        if len(bootstrap_password) < 16 or bootstrap_is_placeholder or bootstrap_password != self.bootstrap_password:
            errors.append("BOOTSTRAP_PASSWORD must be a unique secret of at least 16 characters")
        if jwt_secret == bootstrap_password:
            errors.append("JWT_SECRET and BOOTSTRAP_PASSWORD must be different values")
        database = urlsplit(self.database_url)
        if database.scheme.lower() not in {"postgresql", "postgresql+psycopg"} or not database.path.strip("/"):
            errors.append("DATABASE_URL must use PostgreSQL in staging and production")
        else:
            database_password = unquote(database.password or "")
            password_is_placeholder = database_password.lower().startswith(placeholder_prefixes)
            if database.username != "sps_runtime" or len(database_password) < 24 or password_is_placeholder:
                errors.append("DATABASE_URL must use a dedicated sps_runtime account with a unique password of at least 24 characters")
            if database_password in {jwt_secret, bootstrap_password}:
                errors.append("DATABASE_URL credentials must be different from application authentication secrets")

        keys = [self.app_encryption_key.strip(), *(key.strip() for key in self.app_encryption_previous_keys.split(",") if key.strip())]
        if not keys or not keys[0]:
            errors.append("APP_ENCRYPTION_KEY is required in staging and production")
        else:
            if keys[0] == type(self).model_fields["app_encryption_key"].default:
                errors.append("APP_ENCRYPTION_KEY must not use the built-in development key")
            try:
                for key in keys:
                    Fernet(key.encode("ascii"))
            except (ValueError, UnicodeEncodeError):
                errors.append("APP_ENCRYPTION_KEY and previous keys must be valid Fernet keys")
            if len(set(keys)) != len(keys):
                errors.append("APP_ENCRYPTION_KEY values must be unique")

        if errors:
            raise ValueError("Invalid secure deployment configuration: " + "; ".join(errors))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
