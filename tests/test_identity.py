"""Exercise revocation and delegated account administration against PostgreSQL."""

from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.main import app
from app.models import User
from app.routes.users import preserve_last_admin
from app.security import create_access_token, hash_password

PASSWORD = "identity-fixture-password"


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


def test_password_change_revokes_all_tokens_while_logout_revokes_only_one_session():
    with TestClient(app) as client:
        user_id, old = account(client, "Operator")
        old_login = client.post(
            "/api/v1/auth/login", json={"username": client.get("/api/v1/auth/me", headers=old).json()["username"], "password": PASSWORD}
        )
        other = {"Authorization": f"Bearer {old_login.json()['access_token']}"}
        initial_sessions = client.get("/api/v1/auth/sessions", headers=old)
        assert initial_sessions.status_code == 200 and len(initial_sessions.json()) == 2
        second_id = next(row["session_id"] for row in initial_sessions.json() if not row["is_current"])
        assert client.delete(f"/api/v1/auth/sessions/{second_id}", headers=old).status_code == 204
        assert client.get("/api/v1/auth/me", headers=other).status_code == 401
        assert client.get("/api/v1/auth/me", headers=old).status_code == 200

        other_login = client.post(
            "/api/v1/auth/login", json={"username": client.get("/api/v1/auth/me", headers=old).json()["username"], "password": PASSWORD}
        )
        other = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
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
        with SessionLocal() as db:
            username = db.get(User, user_id).username
        other_login = client.post("/api/v1/auth/login", json={"username": username, "password": "identity-new-password"})
        other_fresh = {"Authorization": f"Bearer {other_login.json()['access_token']}"}
        assert client.post("/api/v1/auth/logout", headers=fresh).status_code == 204
        assert client.get("/api/v1/auth/me", headers=fresh).status_code == 401
        assert client.get("/api/v1/auth/me", headers=other_fresh).status_code == 200
        active_sessions = client.get("/api/v1/auth/sessions", headers=other_fresh)
        assert active_sessions.status_code == 200 and len(active_sessions.json()) == 1
        assert active_sessions.json()[0]["is_current"]
        session_id = active_sessions.json()[0]["session_id"]
        assert client.delete(f"/api/v1/auth/sessions/{session_id}", headers=other_fresh).status_code == 204
        assert client.get("/api/v1/auth/me", headers=other_fresh).status_code == 401
        assert client.post("/api/v1/auth/logout", headers=fresh).status_code == 401
        username = client.post("/api/v1/auth/login", json={"username": "nonexistent", "password": PASSWORD})
        assert username.status_code == 401
        with SessionLocal() as db:
            assert db.get(User, user_id).token_version == 1


def test_session_listing_and_revocation_are_scoped_to_the_authenticated_user():
    with TestClient(app) as client:
        _, operator = account(client, "Operator")
        _, executive = account(client, "Executive")
        operator_sessions = client.get("/api/v1/auth/sessions", headers=operator)
        executive_sessions = client.get("/api/v1/auth/sessions", headers=executive)
        assert operator_sessions.status_code == 200 and len(operator_sessions.json()) == 1
        assert executive_sessions.status_code == 200 and len(executive_sessions.json()) == 1
        operator_session_id = operator_sessions.json()[0]["session_id"]
        assert client.delete(f"/api/v1/auth/sessions/{operator_session_id}", headers=executive).status_code == 404
        assert client.delete("/api/v1/auth/sessions/not-a-session-id", headers=operator).status_code == 422
        assert client.get("/api/v1/auth/me", headers=operator).status_code == 200


def test_signed_token_without_a_persisted_session_is_rejected():
    with TestClient(app) as client:
        user_id, _ = account(client, "Operator")
        with SessionLocal() as db:
            user = db.get(User, user_id)
            assert user is not None
            token = create_access_token(user.id, user.username, user.role, token_version=user.token_version, session_id="f" * 32)
        assert client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


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
