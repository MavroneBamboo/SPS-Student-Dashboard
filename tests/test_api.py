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


def test_student_duplicate_identifier_and_encrypted_round_trip():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "bootstrap-admin", "password": "test-bootstrap-password"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        payload = {"pris_no": "PS-TEST-001", "name": "Protected Test Name", "class_name": "A4 A", "category": "OP", "status": "ACTIVE", "date_of_birth": "2000-01-02"}
        created = client.post("/api/v1/students", json=payload, headers=headers)
        assert created.status_code == 201
        assert created.json()["name"] == "Protected Test Name"
        assert client.post("/api/v1/students", json=payload, headers=headers).status_code == 409
        listed = client.get("/api/v1/students?q=Protected", headers=headers)
        assert listed.status_code == 200
        assert listed.json()[0]["pris_no"] == "PS-TEST-001"
