import json
import logging
import re

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.routes import health


def test_requests_have_opaque_correlation_ids_and_redacted_structured_logs(caplog):
    with TestClient(app) as client, caplog.at_level(logging.INFO, logger="sps.access"):
        first = client.get("/health/live?name=Sensitive%20Student&access_token=do-not-log", headers={"X-Request-ID": "caller-value"})
        second = client.get("/health/live")
        proxy_id = "b" * 32
        proxied = client.get("/health/live", headers={"X-Request-ID": proxy_id})

    assert first.status_code == second.status_code == proxied.status_code == 200
    first_id = first.headers["x-request-id"]
    second_id = second.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", first_id)
    assert re.fullmatch(r"[0-9a-f]{32}", second_id)
    assert first_id != second_id
    assert first_id != "caller-value"
    assert proxied.headers["x-request-id"] == proxy_id

    events = [json.loads(record.message) for record in caplog.records if record.name == "sps.access"]
    assert [event["request_id"] for event in events] == [first_id, second_id, proxy_id]
    assert all(event["event"] == "http.request.completed" for event in events)
    assert all(event["route"] == "/health/live" and event["status_code"] == 200 for event in events)
    assert all(isinstance(event["duration_ms"], (int, float)) and event["duration_ms"] >= 0 for event in events)
    assert "Sensitive Student" not in caplog.text
    assert "do-not-log" not in caplog.text
    assert "caller-value" not in caplog.text


def test_unhandled_errors_return_generic_response_and_log_no_exception_message(monkeypatch, caplog):
    def fail_database_check():
        raise RuntimeError("private database detail")

    monkeypatch.setattr(health, "check_database", fail_database_check)
    with TestClient(app, raise_server_exceptions=False) as client, caplog.at_level(logging.ERROR, logger="sps.access"):
        response = client.get("/health/ready")

    assert response.status_code == 500
    assert response.text == "Internal Server Error"
    request_id = response.headers["x-request-id"]
    event = next(json.loads(record.message) for record in caplog.records if record.name == "sps.access")
    assert event["request_id"] == request_id
    assert event["route"] == "/health/ready"
    assert event["status_code"] == 500
    assert event["error_type"] == "RuntimeError"
    assert "private database detail" not in caplog.text


def test_unhandled_errors_propagate_only_a_sanitized_exception(monkeypatch, caplog):
    def fail_database_check():
        raise RuntimeError("private database detail")

    monkeypatch.setattr(health, "check_database", fail_database_check)
    with TestClient(app) as client, caplog.at_level(logging.ERROR, logger="sps.access"):
        with pytest.raises(RuntimeError, match="Internal Server Error"):
            client.get("/health/ready")

    assert "private database detail" not in caplog.text
