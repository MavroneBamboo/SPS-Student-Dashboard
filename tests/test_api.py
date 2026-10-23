import os

os.environ["DATABASE_URL"] = "sqlite:///./test-sps-dashboard.db"
os.environ["JWT_SECRET"] = "test-secret-that-is-long-enough"
os.environ["BOOTSTRAP_PASSWORD"] = "test-bootstrap-password"

from fastapi.testclient import TestClient

from app.main import app


def test_live_health():
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_bootstrap_login_and_rule_validation():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "bootstrap-admin", "password": "test-bootstrap-password"})
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        payload = {"academic_year": "2026", "target_type": "CLASS", "target_key": "A4 A", "effective_from": "2026-01-01", "rule": {"maxLessonsPerDay": 4}}
        assert client.post("/api/v1/timetable/rules", json=payload, headers=headers).status_code == 201
        assert client.post("/api/v1/timetable/rules", json=payload, headers=headers).status_code == 409
