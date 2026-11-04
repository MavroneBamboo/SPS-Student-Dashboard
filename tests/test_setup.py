import json
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import AuditEvent, SetupState, User
from app.security import hash_password


def test_bootstrap_setup_gates_normal_use_and_atomically_creates_first_it_administrator():
    settings = get_settings()
    bootstrap_password = "setup-flow-bootstrap-password"
    administrator_name = f"setup-first-it-{uuid4().hex[:8]}"
    operator_name = f"setup-operator-{uuid4().hex[:8]}"
    operator_password = "setup-flow-operator-password"
    with SessionLocal() as db:
        setup_event_count = db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action.like("setup.%")))
        bootstrap = db.scalar(select(User).where(func.lower(User.username) == settings.bootstrap_username.lower()))
        bootstrap.password_hash = hash_password(bootstrap_password)
        bootstrap.role = "Superuser"
        bootstrap.is_active = True
        bootstrap.must_change_password = False
        bootstrap.token_version += 1
        for administrator in db.scalars(select(User).where(User.role == "IT Administrator", User.is_active.is_(True))):
            administrator.is_active = False
        operator = User(username=operator_name, password_hash=hash_password(operator_password), role="Operator", is_active=True)
        db.add(operator)
        setup = db.get(SetupState, 1)
        setup.completed = False
        setup.completed_at = None
        setup.completed_by = None
        db.commit()

    temporary_password = "initial-it-admin-temporary-password"
    with TestClient(app) as client:
        assert client.get("/api/v1/setup/status").status_code == 401
        operator_login = client.post("/api/v1/auth/login", json={"username": operator_name, "password": operator_password})
        operator_headers = {"Authorization": f"Bearer {operator_login.json()['access_token']}"}
        assert client.get("/api/v1/setup/status", headers=operator_headers).json() == {"required": True, "can_complete": False}
        assert (
            client.post(
                "/api/v1/setup/complete",
                json={"username": administrator_name, "temporary_password": temporary_password},
                headers=operator_headers,
            ).status_code
            == 403
        )

        bootstrap_login = client.post("/api/v1/auth/login", json={"username": settings.bootstrap_username, "password": bootstrap_password})
        bootstrap_headers = {"Authorization": f"Bearer {bootstrap_login.json()['access_token']}"}
        assert client.get("/api/v1/setup/status", headers=bootstrap_headers).json() == {"required": True, "can_complete": True}
        assert client.get("/api/v1/reports/dashboard", headers=bootstrap_headers).status_code == 403
        assert client.get("/api/v1/users", headers=bootstrap_headers).status_code == 403

        conflict = client.post(
            "/api/v1/setup/complete",
            json={"username": operator_name, "temporary_password": temporary_password},
            headers=bootstrap_headers,
        )
        assert conflict.status_code == 409
        with SessionLocal() as db:
            assert not db.get(SetupState, 1).completed
            assert db.scalar(select(func.count()).select_from(AuditEvent).where(AuditEvent.action.like("setup.%"))) == setup_event_count

        completed = client.post(
            "/api/v1/setup/complete",
            json={"username": administrator_name, "temporary_password": temporary_password},
            headers=bootstrap_headers,
        )
        assert completed.status_code == 200
        assert completed.json()["completed"] is True
        assert completed.json()["administrator"]["role"] == "IT Administrator"
        assert completed.json()["administrator"]["must_change_password"] is True
        assert client.get("/api/v1/setup/status", headers=bootstrap_headers).json() == {"required": False, "can_complete": True}
        assert client.get("/api/v1/reports/dashboard", headers=bootstrap_headers).status_code == 200
        assert (
            client.post(
                "/api/v1/setup/complete",
                json={"username": "second.it.admin", "temporary_password": temporary_password},
                headers=bootstrap_headers,
            ).status_code
            == 409
        )

    with SessionLocal() as db:
        setup = db.get(SetupState, 1)
        administrator = db.scalar(select(User).where(User.username == administrator_name))
        assert setup.completed and setup.completed_by is not None and setup.completed_at is not None
        assert administrator is not None and administrator.must_change_password
        administrator_event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "setup.initial_it_administrator.created", AuditEvent.entity_id == str(administrator.id)
            )
        )
        completion_event = db.scalar(
            select(AuditEvent).where(
                AuditEvent.action == "setup.completed",
                AuditEvent.details_json.like(f'%"administrator_id":{administrator.id}%'),
            )
        )
        assert administrator_event is not None and completion_event is not None
        assert temporary_password not in administrator_event.details_json + completion_event.details_json
        assert json.loads(completion_event.details_json) == {"administrator_id": administrator.id}
