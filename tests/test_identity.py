"""Exercise revocation and delegated account administration against PostgreSQL."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, engine
from app.main import app
from app.models import AuditEvent, User
from app.routes.users import preserve_last_admin
from app.security import hash_password

PASSWORD = "identity-fixture-password"


def test_login_audits_success_and_failures_without_storing_credentials_or_unknown_usernames():
    active_username = f"audit-active-{uuid4().hex[:12]}"
    inactive_username = f"audit-inactive-{uuid4().hex[:12]}"
    unknown_username = f"audit-unknown-{uuid4().hex[:12]}"
    with SessionLocal() as db:
        active = User(username=active_username, password_hash=hash_password(PASSWORD), role="Operator", is_active=True)
        inactive = User(username=inactive_username, password_hash=hash_password(PASSWORD), role="Operator", is_active=False)
        db.add_all([active, inactive])
        db.commit()
        active_id, inactive_id = active.id, inactive.id

    with TestClient(app) as client:
        wrong_password = client.post("/api/v1/auth/login", json={"username": active_username, "password": "wrong-audit-password"})
        inactive_login = client.post("/api/v1/auth/login", json={"username": inactive_username, "password": PASSWORD})
        unknown_login = client.post("/api/v1/auth/login", json={"username": unknown_username, "password": PASSWORD})
        successful_login = client.post("/api/v1/auth/login", json={"username": active_username, "password": PASSWORD})

    assert [response.status_code for response in (wrong_password, inactive_login, unknown_login)] == [401, 401, 401]
    assert {response.json()["detail"] for response in (wrong_password, inactive_login, unknown_login)} == {"Invalid username or password"}
    assert successful_login.status_code == 200
    with SessionLocal() as db:
        events = list(
            db.scalars(
                select(AuditEvent).where(
                    AuditEvent.action.in_(["auth.login.failed", "auth.login.succeeded"]),
                    AuditEvent.entity_id.in_([str(active_id), str(inactive_id), "unknown"]),
                )
            )
        )
    assert {(event.action, event.actor_id, event.entity_type, event.entity_id, event.details_json) for event in events} == {
        ("auth.login.failed", active_id, "user", str(active_id), '{"outcome":"failed"}'),
        ("auth.login.failed", inactive_id, "user", str(inactive_id), '{"outcome":"failed"}'),
        ("auth.login.failed", 0, "authentication_attempt", "unknown", '{"outcome":"failed"}'),
        ("auth.login.succeeded", active_id, "user", str(active_id), '{"outcome":"success"}'),
    }
    assert PASSWORD not in str(events) and "wrong-audit-password" not in str(events)
    assert unknown_username not in str(events)


def test_repeated_account_failures_start_a_bounded_cooldown_and_success_resets_it():
    username = f"cooldown-{uuid4().hex[:12]}"
    with SessionLocal() as db:
        user = User(username=username, password_hash=hash_password(PASSWORD), role="Operator", is_active=True)
        db.add(user)
        db.commit()
        user_id = user.id

    with TestClient(app) as client:
        for _ in range(5):
            failed = client.post("/api/v1/auth/login", json={"username": username, "password": "incorrect"})
            assert failed.status_code == 401
        blocked = client.post("/api/v1/auth/login", json={"username": username, "password": "incorrect"})
        assert blocked.status_code == 401
        successful = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD})
        assert successful.status_code == 200

        for _ in range(5):
            failed = client.post("/api/v1/auth/login", json={"username": username, "password": "incorrect"})
            assert failed.status_code == 401
        with SessionLocal() as db:
            recent_failures = db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.actor_id == user_id,
                    AuditEvent.action == "auth.login.failed",
                    AuditEvent.entity_type == "user",
                )
                .order_by(AuditEvent.id.desc())
                .limit(5)
            ).all()
            assert len(recent_failures) == 5
            expired_at = datetime.now(UTC) - timedelta(minutes=16)
            for event in recent_failures:
                event.created_at = expired_at
            db.commit()

        after_cooldown = client.post("/api/v1/auth/login", json={"username": username, "password": "incorrect"})
        assert after_cooldown.status_code == 401

    with SessionLocal() as db:
        actions = list(
            db.scalars(
                select(AuditEvent.action)
                .where(AuditEvent.actor_id == user_id, AuditEvent.entity_type == "user", AuditEvent.entity_id == str(user_id))
                .order_by(AuditEvent.id)
            )
        )
    assert actions.count("auth.login.blocked") == 1
    assert actions.count("auth.login.succeeded") == 1
    assert actions.count("auth.login.failed") == 11


def test_concurrent_login_failures_cannot_race_past_account_cooldown():
    if engine.dialect.name != "postgresql":
        pytest.skip("Concurrent account cooldown behavior depends on PostgreSQL row locks")
    username = f"cooldown-race-{uuid4().hex[:12]}"
    with SessionLocal() as db:
        user = User(username=username, password_hash=hash_password(PASSWORD), role="Operator", is_active=True)
        db.add(user)
        db.commit()
        user_id = user.id

    barrier = Barrier(7)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=7) as executor:

        def fail_login():
            barrier.wait(timeout=10)
            return client.post("/api/v1/auth/login", json={"username": username, "password": "incorrect"})

        responses = list(executor.map(lambda _: fail_login(), range(7)))

    assert all(response.status_code == 401 for response in responses)
    with SessionLocal() as db:
        actions = list(
            db.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.actor_id == user_id,
                    AuditEvent.entity_type == "user",
                    AuditEvent.entity_id == str(user_id),
                )
            )
        )
    assert actions.count("auth.login.failed") == 5
    assert actions.count("auth.login.blocked") == 2


def account(client: TestClient, role: str, password: str = PASSWORD) -> tuple[int, dict]:
    username = f"identity-{uuid4().hex[:15]}"
    with SessionLocal() as db:
        row = User(username=username, password_hash=hash_password(password), role=role, must_change_password=False, is_active=True)
        db.add(row)
        db.commit()
        user_id = row.id
    login = client.post("/api/v1/auth/login", json={"username": username.upper(), "password": password})
    assert login.status_code == 200
    return user_id, {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_password_change_and_logout_revoke_all_existing_account_tokens():
    with TestClient(app) as client:
        user_id, old = account(client, "Operator")
        old_login = client.post(
            "/api/v1/auth/login", json={"username": client.get("/api/v1/auth/me", headers=old).json()["username"], "password": PASSWORD}
        )
        other = {"Authorization": f"Bearer {old_login.json()['access_token']}"}
        changed = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": PASSWORD, "new_password": "identity-new-password"},
            headers=old,
        )
        assert changed.status_code == 200
        assert client.get("/api/v1/auth/me", headers=old).status_code == 401
        assert client.get("/api/v1/auth/me", headers=other).status_code == 401
        fresh = {"Authorization": f"Bearer {changed.json()['access_token']}"}
        assert client.get("/api/v1/auth/me", headers=fresh).json()["sub"] == str(user_id)
        assert client.post("/api/v1/auth/logout", headers=fresh).status_code == 204
        assert client.get("/api/v1/auth/me", headers=fresh).status_code == 401
        assert client.post("/api/v1/auth/logout", headers=fresh).status_code == 401
        username = client.post("/api/v1/auth/login", json={"username": "nonexistent", "password": PASSWORD})
        assert username.status_code == 401
        with SessionLocal() as db:
            assert db.get(User, user_id).token_version == 2


def test_it_admin_can_manage_named_users_but_never_superuser():
    with TestClient(app) as client:
        it_id, it = account(client, "IT Administrator")
        root_id, root = account(client, "Superuser")
        listed = client.get("/api/v1/users", headers=it)
        assert listed.status_code == 200
        assert root_id not in {row["id"] for row in listed.json()}
        root_username = client.get("/api/v1/auth/me", headers=root).json()["username"]
        assert client.patch(f"/api/v1/users/{root_id}", json={"is_active": False}, headers=it).status_code == 403
        assert (
            client.post(
                f"/api/v1/users/{root_id}/reset-password", json={"temporary_password": "new-temporary-password"}, headers=it
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/users", json={"username": root_username.upper(), "role": "Operator", "temporary_password": PASSWORD}, headers=it
            ).status_code
            == 409
        )
        assert (
            client.post(
                "/api/v1/users",
                json={"username": f"forbidden-{uuid4().hex[:8]}", "role": "Superuser", "temporary_password": PASSWORD},
                headers=it,
            ).status_code
            == 403
        )
        username = f"operator-{uuid4().hex[:10]}"
        created = client.post("/api/v1/users", json={"username": username, "role": "Operator", "temporary_password": PASSWORD}, headers=it)
        assert created.status_code == 201
        user_id = created.json()["id"]
        assert client.patch(f"/api/v1/users/{user_id}", json={"role": "Superuser"}, headers=it).status_code == 403
        assert client.patch(f"/api/v1/users/{it_id}", json={"is_active": False}, headers=it).status_code == 422
        assert client.patch(f"/api/v1/users/{root_id}", json={"is_active": False}, headers=root).status_code == 422
        assert client.get("/api/v1/users", headers=it).status_code == 200


def test_last_active_administrator_of_each_kind_is_preserved():
    engine = create_engine("sqlite://")
    User.__table__.create(engine)
    with Session(engine) as db:
        for role in ("Superuser", "IT Administrator"):
            row = User(username=role, password_hash="unused", role=role, must_change_password=False, is_active=True)
            db.add(row)
            db.flush()
            try:
                preserve_last_admin(db, row, {"is_active": False})
            except HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError(f"Last {role} was not protected")
    engine.dispose()


def test_admin_reset_forces_rotation_revokes_tokens_and_excludes_secret_from_audit():
    with TestClient(app) as client:
        _, it = account(client, "IT Administrator")
        user_id, operator = account(client, "Operator")
        assert client.get("/api/v1/reports/dashboard", headers=operator).status_code == 200
        assert (
            client.post(
                f"/api/v1/users/{user_id}/reset-password",
                json={"temporary_password": "fresh-temporary-password"},
                headers=it,
            ).status_code
            == 204
        )
        assert client.get("/api/v1/auth/me", headers=operator).status_code == 401
        with SessionLocal() as db:
            username = db.get(User, user_id).username
        login = client.post("/api/v1/auth/login", json={"username": username, "password": "fresh-temporary-password"})
        assert login.status_code == 200 and login.json()["must_change_password"]
        fresh = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/api/v1/reports/dashboard", headers=fresh).status_code == 403
        assert (
            client.post(
                "/api/v1/users", json={"username": "blocked", "role": "Operator", "temporary_password": PASSWORD}, headers=fresh
            ).status_code
            == 403
        )
        events = client.get("/api/v1/reports/audit", headers=it).json()
        assert any(event["action"] == "user.password.reset" and event["entity_id"] == str(user_id) for event in events)
        assert "fresh-temporary-password" not in str(events)
        assert client.patch(f"/api/v1/users/{user_id}", json={"role": "Executive"}, headers=it).status_code == 200
        assert client.get("/api/v1/auth/me", headers=fresh).status_code == 401
