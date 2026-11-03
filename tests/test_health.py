from types import SimpleNamespace

import pytest

from app.config import get_settings
from app.routes import health


def test_ready_reports_deployed_build_revision(monkeypatch):
    monkeypatch.setattr(health, "check_database", lambda: None)
    monkeypatch.setattr(health, "get_settings", lambda: SimpleNamespace(app_build_sha="a" * 40))

    assert health.ready() == {"status": "ready", "database": "ok", "revision": "a" * 40}


def test_ready_checks_database_before_reporting_revision(monkeypatch):
    def unavailable_database():
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(health, "check_database", unavailable_database)
    monkeypatch.setattr(health, "get_settings", lambda: SimpleNamespace(app_build_sha="b" * 40))

    with pytest.raises(RuntimeError, match="database unavailable"):
        health.ready()


def test_build_revision_comes_from_compose_environment(monkeypatch):
    revision = "c" * 40
    monkeypatch.setenv("APP_BUILD_SHA", revision)
    get_settings.cache_clear()
    try:
        assert get_settings().app_build_sha == revision
    finally:
        get_settings.cache_clear()
