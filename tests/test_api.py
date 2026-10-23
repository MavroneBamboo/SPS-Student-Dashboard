import os
import csv
import io

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


def test_attendance_session_record_duplicate_and_correction_reason():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "bootstrap-admin", "password": "test-bootstrap-password"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        student = {"pris_no": "PS-ATT-001", "name": "Attendance Student", "class_name": "TM1 LNP 1", "category": "OP", "status": "ACTIVE"}
        assert client.post("/api/v1/students", json=student, headers=headers).status_code == 201
        session = client.post("/api/v1/attendance/sessions", json={"session_date": "2026-10-23", "session_type": "MORNING", "class_name": "TM1 LNP 1", "expected_count": 1}, headers=headers)
        assert session.status_code == 201
        session_id = session.json()["id"]
        record_payload = {"pris_no": "PS-ATT-001", "attendance_status": "PRESENT"}
        record = client.post(f"/api/v1/attendance/sessions/{session_id}/records", json=record_payload, headers=headers)
        assert record.status_code == 201
        assert client.post(f"/api/v1/attendance/sessions/{session_id}/records", json=record_payload, headers=headers).status_code == 409
        correction = client.patch(f"/api/v1/attendance/records/{record.json()['id']}", json={"pris_no": "PS-ATT-001", "attendance_status": "ABSENT"}, headers=headers)
        assert correction.status_code == 422
        correction = client.patch(f"/api/v1/attendance/records/{record.json()['id']}", json={"pris_no": "PS-ATT-001", "attendance_status": "ABSENT", "correction_reason": "Verified against paper register"}, headers=headers)
        assert correction.status_code == 200
        assert client.get(f"/api/v1/attendance/sessions/{session_id}/records", headers=headers).json()[0]["attendance_status"] == "ABSENT"
        assert client.post(f"/api/v1/attendance/sessions/{session_id}/close", headers=headers).status_code == 200
        assert client.patch(f"/api/v1/attendance/records/{record.json()['id']}", json={"pris_no": "PS-ATT-001", "attendance_status": "PRESENT", "correction_reason": "Correction attempted after close"}, headers=headers).status_code == 409


def test_dashboard_export_and_audit_are_committed_data_views():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "bootstrap-admin", "password": "test-bootstrap-password"})
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        student = {"pris_no": "PS-REPORT-001", "name": "Report Student", "class_name": "REPORT CLASS", "category": "OP", "status": "ACTIVE"}
        client.post("/api/v1/students", json=student, headers=headers)
        session = client.post("/api/v1/attendance/sessions", json={"session_date": "2026-10-22", "session_type": "AFTERNOON", "class_name": "REPORT CLASS", "expected_count": 2}, headers=headers).json()
        client.post(f"/api/v1/attendance/sessions/{session['id']}/records", json={"pris_no": "PS-REPORT-001", "attendance_status": "PRESENT"}, headers=headers)

        dashboard = client.get("/api/v1/reports/dashboard?class_name=REPORT%20CLASS&date_from=2026-10-01&date_to=2026-10-31", headers=headers)
        assert dashboard.status_code == 200
        result = dashboard.json()
        assert result["students"]["active"] == 1
        assert result["students"]["by_category"] == {"OP": 1}
        assert result["attendance"]["missing"] == 1
        assert result["attendance"]["rate"] == 50.0

        export = client.get("/api/v1/reports/attendance.csv?class_name=REPORT%20CLASS", headers=headers)
        assert export.status_code == 200
        assert list(csv.reader(io.StringIO(export.text)))[1][3:] == ["PS-REPORT-001", "Report Student", "PRESENT"]
        assert client.get("/api/v1/reports/audit", headers=headers).status_code == 200
