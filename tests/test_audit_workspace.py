import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import AuditEvent, User
from app.security import hash_password


def _account(role: str) -> tuple[str, str, str]:
    username = f"audit-{role.lower().replace(' ', '-')}-{uuid4().hex[:10]}"
    password = "audit-workspace-password"
    with SessionLocal() as db:
        user = User(username=username, password_hash=hash_password(password), role=role, must_change_password=False, is_active=True)
        db.add(user)
        db.commit()
        return str(user.id), username, password


def _headers(client: TestClient, username: str, password: str) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_audit_api_is_admin_only_filterable_and_pageable():
    actor_id, admin_name, admin_password = _account("IT Administrator")
    _, operator_name, operator_password = _account("Operator")
    _, executive_name, executive_password = _account("Executive")
    marker = uuid4().hex
    actions = [f"audit.workspace.{marker}.{index}" for index in range(3)]
    with SessionLocal() as db:
        now = datetime.now(UTC)
        db.add_all(
            [
                AuditEvent(
                    actor_id=int(actor_id),
                    action=action,
                    entity_type="audit_workspace_test",
                    entity_id=f"{marker}-{index}",
                    details_json=json.dumps({"index": index}),
                    created_at=now + timedelta(seconds=index),
                )
                for index, action in enumerate(actions)
            ]
        )
        db.commit()

    with TestClient(app) as client:
        admin = _headers(client, admin_name, admin_password)
        page = client.get(
            "/api/v1/reports/audit", params={"actor_id": actor_id, "entity_type": "audit_workspace_test", "limit": 2}, headers=admin
        )
        assert page.status_code == 200
        assert [event["action"] for event in page.json()] == [actions[2], actions[1]]
        assert all(event["actor_username"] == admin_name for event in page.json())

        next_page = client.get(
            "/api/v1/reports/audit",
            params={"actor_id": actor_id, "entity_type": "audit_workspace_test", "limit": 2, "offset": 2},
            headers=admin,
        )
        assert [event["action"] for event in next_page.json()] == [actions[0]]
        filtered = client.get("/api/v1/reports/audit", params={"action": actions[1], "actor_id": actor_id}, headers=admin)
        assert [event["action"] for event in filtered.json()] == [actions[1]]
        assert filtered.json()[0]["details"] == {"index": 1}

        for username, password in ((operator_name, operator_password), (executive_name, executive_password)):
            assert client.get("/api/v1/reports/audit", headers=_headers(client, username, password)).status_code == 403
        assert client.get("/api/v1/reports/audit?offset=-1", headers=admin).status_code == 422
        assert client.get("/api/v1/reports/audit?actor_id=0", headers=admin).status_code == 422
