import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.config import Settings


def production_settings(**overrides) -> Settings:
    values = {
        "app_env": "production",
        "database_url": "postgresql+psycopg://sps_runtime:runtime-secret@db:5432/sps_dashboard",
        "jwt_secret": "a-production-jwt-signing-secret-with-more-than-32-characters",
        "bootstrap_password": "production-bootstrap-secret-987654",
        "app_encryption_key": Fernet.generate_key().decode(),
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_production_configuration_accepts_valid_secrets_and_postgresql():
    settings = production_settings()

    assert settings.app_env == "production"
    assert settings.database_url.startswith("postgresql+psycopg://")


@pytest.mark.parametrize(
    "overrides",
    [
        {"database_url": "sqlite:///./sps-dashboard.db"},
        {"database_url": "postgresql://sps_runtime:secret@db:5432/sps_dashboard"},
        {"database_url": "postgresql+psycopg:///sps_dashboard"},
        {"jwt_secret": "short"},
        {"jwt_secret": "development-only-change-me"},
        {"bootstrap_password": "short"},
        {"bootstrap_password": "change-this-on-first-run"},
        {"app_encryption_key": "not-a-fernet-key"},
        {"app_encryption_key": "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="},
        {"app_encryption_previous_keys": "not-a-fernet-key"},
    ],
)
def test_production_configuration_rejects_weak_or_invalid_values(overrides):
    with pytest.raises(ValidationError, match="Invalid production configuration"):
        production_settings(**overrides)


def test_production_configuration_rejects_duplicate_encryption_keys():
    active_key = Fernet.generate_key().decode()

    with pytest.raises(ValidationError, match="encryption keys must be unique"):
        production_settings(app_encryption_key=active_key, app_encryption_previous_keys=active_key)


def test_invalid_production_configuration_does_not_echo_secret_values():
    secret_value = "TOPSECRET-VALUE-1234567"

    with pytest.raises(ValidationError) as error:
        production_settings(jwt_secret=secret_value)

    assert secret_value not in str(error.value)


def test_development_configuration_keeps_local_defaults_usable():
    settings = Settings(_env_file=None, app_env="development", database_url="sqlite:///./sps-dashboard.db")

    assert settings.database_url.startswith("sqlite:")


@pytest.mark.parametrize("days", [-1, 3651])
def test_student_import_retention_period_is_bounded(days):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, app_env="development", student_import_retention_days=days)


def test_student_import_retention_is_disabled_by_default():
    settings = Settings(_env_file=None, app_env="development")

    assert settings.student_import_retention_days == 0
