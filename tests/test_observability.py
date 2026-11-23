import json
import logging
import re
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import SessionLocal
from app.main import app
from app.models import AuditEvent, User
from app.routes import health
from app.security import hash_password


def test_requests_receive_ids_and_emit_redacted_structured_access_logs(caplog):
    invalid_id = "caller-value"
    proxy_id = "b" * 32
    with TestClient(app) as client, caplog.at_level(logging.INFO, logger="sps.access"):
        invalid = client.get("/health/live?name=Sensitive%20Student&access_token=do-not-log", headers={"X-Request-ID": invalid_id})
        generated = client.get("/health/live")
        proxied = client.get("/health/live", headers={"X-Request-ID": proxy_id})

    assert invalid.status_code == generated.status_code == proxied.status_code == 200
    invalid_request_id = invalid.headers["x-request-id"]
    generated_request_id = generated.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", invalid_request_id)
    assert re.fullmatch(r"[0-9a-f]{32}", generated_request_id)
    assert invalid_request_id != invalid_id
    assert invalid_request_id != generated_request_id
    assert proxied.headers["x-request-id"] == proxy_id

    events = [json.loads(record.message) for record in caplog.records if record.name == "sps.access"]
    assert [event["request_id"] for event in events] == [invalid_request_id, generated_request_id, proxy_id]
    assert all(event["event"] == "http.request.completed" for event in events)
    assert all(event["route"] == "/health/live" and event["status_code"] == 200 for event in events)
    assert all(isinstance(event["duration_ms"], (int, float)) and event["duration_ms"] >= 0 for event in events)
    assert "Sensitive Student" not in caplog.text
    assert "do-not-log" not in caplog.text
    assert invalid_id not in caplog.text


def test_login_audit_events_share_the_request_correlation_id():
    username = f"correlation-{uuid4().hex[:12]}"
    password = "correlation-test-password"
    with SessionLocal() as db:
        user = User(username=username, password_hash=hash_password(password), role="Operator", must_change_password=False, is_active=True)
        db.add(user)
        db.commit()
        user_id = user.id

    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})

    assert response.status_code == 200
    request_id = response.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", request_id)
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuditEvent).where(
                AuditEvent.actor_id == user_id,
                AuditEvent.action.in_(("auth.session.created", "auth.login.succeeded")),
            )
        ).all()
    assert {row.action for row in rows} == {"auth.session.created", "auth.login.succeeded"}
    assert all(row.request_id == request_id for row in rows)


def test_unhandled_errors_return_generic_response_and_redacted_log(monkeypatch, caplog):
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
