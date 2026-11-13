import pytest

from app.tde_setup import _provider_settings


def _configure_vault(monkeypatch, *, app_env, url):
    monkeypatch.setenv("APP_ENV", app_env)
    monkeypatch.setenv("TDE_PROVIDER", "vault")
    monkeypatch.setenv("TDE_PROVIDER_NAME", "sps-key-provider")
    monkeypatch.setenv("TDE_VAULT_URL", url)


def test_production_vault_requires_https(monkeypatch):
    _configure_vault(monkeypatch, app_env="production", url="http://vault.internal:8200")

    with pytest.raises(RuntimeError, match="Production requires HTTPS"):
        _provider_settings()


def test_production_vault_accepts_https(monkeypatch):
    _configure_vault(monkeypatch, app_env="production", url="https://vault.internal:8200")

    assert _provider_settings() == ("sps-key-provider", "vault")


@pytest.mark.parametrize(
    "url",
    [
        "",
        "vault.internal:8200",
        "file:///tmp/vault",
        "https://user:secret@vault.internal:8200",
        "https://vault.internal:bad-port",
        "https://vault.internal:8200?token=secret",
        "https://vault.internal:8200/#fragment",
    ],
)
def test_vault_url_rejects_malformed_or_credential_bearing_values(monkeypatch, url):
    _configure_vault(monkeypatch, app_env="development", url=url)

    with pytest.raises(RuntimeError, match=r"valid Vault HTTP\(S\) URL"):
        _provider_settings()


def test_development_vault_may_use_http_for_local_test_services(monkeypatch):
    _configure_vault(monkeypatch, app_env="development", url="http://vault:8200")

    assert _provider_settings() == ("sps-key-provider", "vault")
