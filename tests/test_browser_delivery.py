from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import User


def test_browser_assets_are_delivered_locally_with_restrictive_headers():
    with TestClient(app) as client:
        root = client.get("/", follow_redirects=False)
        assert root.status_code == 303 and root.headers["location"] == "/ui/"
        for path, content_type in (
            ("/ui/", "text/html"),
            ("/ui/app.js", "javascript"),
            ("/ui/reference-data.js", "javascript"),
            ("/ui/app.css", "text/css"),
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert content_type in response.headers["content-type"]
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-frame-options"] == "DENY"
            assert response.headers["x-content-type-options"] == "nosniff"
            policy = response.headers["content-security-policy"]
            assert "'unsafe-inline'" not in policy and "'unsafe-eval'" not in policy
            assert "frame-ancestors 'none'" in policy
        html = client.get("/ui/").text
        assert 'src="/ui/app.js"' in html and 'href="/ui/app.css"' in html
        assert "https://" not in html and "http://" not in html
        assert client.get("/ui/%2e%2e/pyproject.toml").status_code == 404
        assert client.get("/ui/missing.js").status_code == 404


def test_identity_endpoint_returns_current_server_state_without_granting_rotation_bypass(lesson_context):
    client, headers, _ = lesson_context
    identity = client.get("/api/v1/auth/me", headers=headers["operator"])
    assert identity.status_code == 200
    assert set(identity.json()) == {"sub", "username", "role", "must_change_password"}
    assert identity.json()["role"] == "Operator"
    user_id = int(identity.json()["sub"])
    with SessionLocal() as db:
        user = db.get(User, user_id)
        user.role = "Executive"
        user.must_change_password = True
        db.commit()
    current = client.get("/api/v1/auth/me", headers=headers["operator"])
    assert current.json()["role"] == "Executive" and current.json()["must_change_password"]
    assert client.get("/api/v1/reports/dashboard", headers=headers["operator"]).status_code == 403
    with SessionLocal() as db:
        db.get(User, user_id).is_active = False
        db.commit()
    assert client.get("/api/v1/auth/me", headers=headers["operator"]).status_code == 401
    assert client.get("/api/v1/auth/me").status_code == 401
