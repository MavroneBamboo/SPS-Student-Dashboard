import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings


def _staging_settings(**overrides):
    values = {
        "_env_file": None,
        "app_env": "staging",
        "database_url": "postgresql+psycopg://sps_runtime:runtime-password-with-at-least-24-characters@db:5432/sps_dashboard",
        "jwt_secret": "unique-jwt-secret-with-more-than-32-bytes",
        "bootstrap_password": "unique-bootstrap-password",
        "app_encryption_key": Fernet.generate_key().decode("ascii"),
    }
    values.update(overrides)
    return Settings(**values)


def test_development_settings_keep_local_defaults():
    settings = Settings(_env_file=None)
    assert settings.app_env == "development"
    assert settings.database_url.startswith("sqlite:")


def test_staging_accepts_postgres_and_strong_secrets():
    settings = _staging_settings()
    assert settings.app_env == "staging"


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"jwt_secret": "short"}, "JWT_SECRET"),
        ({"jwt_secret": "development-only-change-me"}, "JWT_SECRET"),
        ({"jwt_secret": "ci-only-jwt-secret-that-is-long-enough"}, "JWT_SECRET"),
        ({"bootstrap_password": "change-this-on-first-run"}, "BOOTSTRAP_PASSWORD"),
        ({"bootstrap_password": "short"}, "BOOTSTRAP_PASSWORD"),
        ({"bootstrap_password": "ci-only-bootstrap-password"}, "BOOTSTRAP_PASSWORD"),
        ({"database_url": "sqlite:///./sps-dashboard.db"}, "DATABASE_URL"),
        ({"database_url": "postgresql+psycopg://sps_app:long-enough-admin-password@db:5432/sps_dashboard"}, "sps_runtime"),
        ({"database_url": "postgresql+psycopg://sps_runtime:short@db:5432/sps_dashboard"}, "24 characters"),
        ({"database_url": "postgresql+psycopg://sps_runtime:change-this-runtime-password@db:5432/sps_dashboard"}, "24 characters"),
        (
            {"jwt_secret": "runtime-password-with-at-least-24-characters"},
            "different from application authentication secrets",
        ),
        ({"app_encryption_key": "invalid-key"}, "Fernet"),
        ({"app_encryption_key": Settings.model_fields["app_encryption_key"].default}, "built-in development key"),
        ({"app_encryption_key": Fernet.generate_key().decode(), "app_encryption_previous_keys": "invalid-key"}, "Fernet"),
        ({"app_encryption_key": ""}, "APP_ENCRYPTION_KEY"),
        ({"access_token_minutes": 61}, "access_token_minutes"),
    ],
)
def test_staging_rejects_unsafe_configuration(override, message):
    with pytest.raises(ValidationError, match=message):
        _staging_settings(**override)


def test_production_rejects_duplicate_encryption_keys():
    key = Fernet.generate_key().decode("ascii")
    with pytest.raises(ValidationError, match="unique"):
        _staging_settings(app_env="production", app_encryption_key=key, app_encryption_previous_keys=key)


def test_staging_requires_distinct_jwt_and_bootstrap_secrets():
    password = "same-long-random-secret-value"
    with pytest.raises(ValidationError, match="different values"):
        _staging_settings(jwt_secret=password, bootstrap_password=password)


def test_configuration_validation_errors_do_not_include_secret_values():
    marker = "private-secret-marker"
    with pytest.raises(ValidationError) as error:
        _staging_settings(jwt_secret=marker)
    assert marker not in str(error.value)
    assert "runtime-password-with-at-least-24-characters" not in str(error.value)
