import csv
import io
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test-sps-dashboard.db")
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough")  # gitleaks:allow
os.environ.setdefault("BOOTSTRAP_PASSWORD", "test-bootstrap-password")

from fastapi.testclient import TestClient

from app.main import app

INITIAL_BOOTSTRAP_PASSWORD = os.environ["BOOTSTRAP_PASSWORD"]
ROTATED_BOOTSTRAP_PASSWORD = "test-bootstrap-password-rotated"


def login_headers(client):
    login = None
    password = None
    for candidate in (INITIAL_BOOTSTRAP_PASSWORD, ROTATED_BOOTSTRAP_PASSWORD):
        response = client.post("/api/v1/auth/login", json={"username": "bootstrap-admin", "password": candidate})
        if response.status_code == 200:
            login = response
            password = candidate
            break
    assert login is not None
    if login.json()["must_change_password"]:
        changed = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": password, "new_password": ROTATED_BOOTSTRAP_PASSWORD},
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
        )
        assert changed.status_code == 200
        login = changed
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_live_health():
    with TestClient(app) as client:
        response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_bootstrap_login_and_rule_validation():
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": "bootstrap-admin", "password": INITIAL_BOOTSTRAP_PASSWORD})
        assert login.status_code == 200
        assert login.json()["must_change_password"] is True
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        payload = {
            "academic_year": "2026",
            "target_type": "CLASS",
            "target_key": "A4 A",
            "effective_from": "2026-01-01",
            "rule": {"maxLessonsPerDay": 4},
        }
        assert client.post("/api/v1/timetable/rules", json=payload, headers=headers).status_code == 403
        changed = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": INITIAL_BOOTSTRAP_PASSWORD, "new_password": ROTATED_BOOTSTRAP_PASSWORD},
            headers=headers,
        )
        assert changed.status_code == 200
        assert changed.json()["must_change_password"] is False
        headers = {"Authorization": f"Bearer {changed.json()['access_token']}"}
        assert client.post("/api/v1/timetable/rules", json=payload, headers=headers).status_code == 201
        assert client.post("/api/v1/timetable/rules", json=payload, headers=headers).status_code == 409
        created_user = client.post(
            "/api/v1/users",
            json={"username": "operator.one", "temporary_password": "operator-temporary-password", "role": "Operator"},
            headers=headers,
        )
        assert created_user.status_code == 201
        assert created_user.json()["must_change_password"] is True
        assert (
            client.post(
                "/api/v1/users",
                json={"username": "OPERATOR.ONE", "temporary_password": "operator-temporary-password", "role": "Operator"},
                headers=headers,
            ).status_code
            == 409
        )
        assert client.get("/api/v1/users", headers=headers).status_code == 200
        assert (
            client.patch(f"/api/v1/users/{created_user.json()['id']}", json={"role": "Executive"}, headers=headers).json()["role"]
            == "Executive"
        )
        admin_id = next(row["id"] for row in client.get("/api/v1/users", headers=headers).json() if row["username"] == "bootstrap-admin")
        assert client.patch(f"/api/v1/users/{admin_id}", json={"is_active": False}, headers=headers).status_code == 422
        assert client.patch(f"/api/v1/users/{admin_id}", json={"role": "Executive"}, headers=headers).status_code == 409


def test_student_duplicate_identifier_and_encrypted_round_trip():
    with TestClient(app) as client:
        headers = login_headers(client)
        payload = {
            "pris_no": "PS-TEST-001",
            "name": "Protected Test Name",
            "class_name": "A4 A",
            "category": "OP",
            "status": "ACTIVE",
            "date_of_birth": "2000-01-02",
        }
        created = client.post("/api/v1/students", json=payload, headers=headers)
        assert created.status_code == 201
        assert created.json()["name"] == "Protected Test Name"
        assert client.post("/api/v1/students", json=payload, headers=headers).status_code == 409
        listed = client.get("/api/v1/students?q=Protected", headers=headers)
        assert listed.status_code == 200
        assert listed.json()[0]["pris_no"] == "PS-TEST-001"
        student_id = created.json()["id"]
        updated = client.patch(
            f"/api/v1/students/{student_id}",
            json={"name": "Updated Protected Name", "status": "INACTIVE", "status_effective": "2026-10-23"},
            headers=headers,
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "Updated Protected Name"
        history = client.get(f"/api/v1/students/{student_id}/status-history", headers=headers)
        assert history.status_code == 200
        assert [entry["new_status"] for entry in history.json()] == ["ACTIVE", "INACTIVE"]
        assert client.patch(f"/api/v1/students/{student_id}", json={}, headers=headers).status_code == 422

        executive_created = client.post(
            "/api/v1/users",
            json={"username": "executive.one", "temporary_password": "executive-temporary-password", "role": "Executive"},
            headers=headers,
        )
        assert executive_created.status_code == 201
        executive_login = client.post("/api/v1/auth/login", json={"username": "executive.one", "password": "executive-temporary-password"})
        assert executive_login.status_code == 200
        executive_changed = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "executive-temporary-password", "new_password": "executive-permanent-password"},
            headers={"Authorization": f"Bearer {executive_login.json()['access_token']}"},
        )
        assert executive_changed.status_code == 200
        executive_headers = {"Authorization": f"Bearer {executive_changed.json()['access_token']}"}
        assert client.get("/api/v1/students", headers=executive_headers).status_code == 403
        assert client.get(f"/api/v1/students/{student_id}/status-history", headers=executive_headers).status_code == 403
        assert client.get("/api/v1/reports/dashboard", headers=executive_headers).status_code == 200
        assert client.get("/api/v1/users", headers=executive_headers).status_code == 403
        assert (
            client.patch(f"/api/v1/users/{executive_created.json()['id']}", json={"is_active": False}, headers=headers).status_code == 200
        )
        assert client.get("/api/v1/reports/dashboard", headers=executive_headers).status_code == 401


def test_attendance_session_record_duplicate_and_correction_reason():
    with TestClient(app) as client:
        headers = login_headers(client)
        student = {"pris_no": "PS-ATT-001", "name": "Attendance Student", "class_name": "TM1 LNP 1", "category": "OP", "status": "ACTIVE"}
        assert client.post("/api/v1/students", json=student, headers=headers).status_code == 201
        session = client.post(
            "/api/v1/attendance/sessions",
            json={"session_date": "2026-10-23", "session_type": "MORNING", "class_name": "TM1 LNP 1", "expected_count": 1},
            headers=headers,
        )
        assert session.status_code == 201
        session_id = session.json()["id"]
        record_payload = {"pris_no": "PS-ATT-001", "attendance_status": "PRESENT"}
        record = client.post(f"/api/v1/attendance/sessions/{session_id}/records", json=record_payload, headers=headers)
        assert record.status_code == 201
        assert client.post(f"/api/v1/attendance/sessions/{session_id}/records", json=record_payload, headers=headers).status_code == 409
        correction = client.patch(
            f"/api/v1/attendance/records/{record.json()['id']}",
            json={"pris_no": "PS-ATT-001", "attendance_status": "ABSENT"},
            headers=headers,
        )
        assert correction.status_code == 422
        correction = client.patch(
            f"/api/v1/attendance/records/{record.json()['id']}",
            json={"pris_no": "PS-ATT-001", "attendance_status": "ABSENT", "correction_reason": "Verified against paper register"},
            headers=headers,
        )
        assert correction.status_code == 200
        assert client.get(f"/api/v1/attendance/sessions/{session_id}/records", headers=headers).json()[0]["attendance_status"] == "ABSENT"
        assert client.post(f"/api/v1/attendance/sessions/{session_id}/close", headers=headers).status_code == 200
        assert (
            client.patch(
                f"/api/v1/attendance/records/{record.json()['id']}",
                json={"pris_no": "PS-ATT-001", "attendance_status": "PRESENT", "correction_reason": "Correction attempted after close"},
                headers=headers,
            ).status_code
            == 409
        )
        actions = {event["action"] for event in client.get("/api/v1/reports/audit", headers=headers).json()}
        assert {
            "attendance.session.created",
            "attendance.record.created",
            "attendance.record.corrected",
            "attendance.session.closed",
        } <= actions


def test_dashboard_export_and_audit_are_committed_data_views():
    with TestClient(app) as client:
        headers = login_headers(client)
        student = {"pris_no": "PS-REPORT-001", "name": "Report Student", "class_name": "REPORT CLASS", "category": "OP", "status": "ACTIVE"}
        client.post("/api/v1/students", json=student, headers=headers)
        session = client.post(
            "/api/v1/attendance/sessions",
            json={"session_date": "2026-10-22", "session_type": "AFTERNOON", "class_name": "REPORT CLASS", "expected_count": 2},
            headers=headers,
        ).json()
        client.post(
            f"/api/v1/attendance/sessions/{session['id']}/records",
            json={"pris_no": "PS-REPORT-001", "attendance_status": "PRESENT"},
            headers=headers,
        )

        dashboard = client.get(
            "/api/v1/reports/dashboard?class_name=REPORT%20CLASS&date_from=2026-10-01&date_to=2026-10-31", headers=headers
        )
        assert dashboard.status_code == 200
        result = dashboard.json()
        assert result["students"]["active"] == 1
        assert result["students"]["by_category"] == {"OP": 1}
        assert result["attendance"]["missing"] == 1
        assert result["attendance"]["rate"] == 50.0

        export = client.get("/api/v1/reports/attendance.csv?class_name=REPORT%20CLASS", headers=headers)
        assert export.status_code == 200
        assert list(csv.reader(io.StringIO(export.text)))[1][3:] == ["PS-REPORT-001", "Report Student", "PRESENT"]
        audit = client.get("/api/v1/reports/audit", headers=headers)
        assert audit.status_code == 200
        actions = {event["action"] for event in audit.json()}
        assert {"student.created", "attendance.session.created", "attendance.record.created"} <= actions
        assert all("pris_no" not in event["details"] for event in audit.json())


def test_timetable_resources_clusters_period_overrides_and_lunch_invariant():
    with TestClient(app) as client:
        superuser_headers = login_headers(client)
        created_user = client.post(
            "/api/v1/users",
            json={"username": "timetable.admin", "temporary_password": "timetable-admin-temporary", "role": "IT Administrator"},
            headers=superuser_headers,
        )
        assert created_user.status_code == 201
        admin_login = client.post("/api/v1/auth/login", json={"username": "timetable.admin", "password": "timetable-admin-temporary"})
        assert admin_login.status_code == 200
        changed_password = client.post(
            "/api/v1/auth/change-password",
            json={"current_password": "timetable-admin-temporary", "new_password": "timetable-admin-permanent"},
            headers={"Authorization": f"Bearer {admin_login.json()['access_token']}"},
        )
        assert changed_password.status_code == 200
        headers = {"Authorization": f"Bearer {changed_password.json()['access_token']}"}
        availability = {day: ["P1", "P2", "P3", "P4"] for day in ("MON", "TUE", "WED", "THU", "FRI")}
        teacher_payload = {"short_code": "teach-a", "full_name": "Teacher A", "is_adjunct": True, "availability": availability}
        assert client.post("/api/v1/timetable/teachers", json=teacher_payload, headers=superuser_headers).status_code == 403
        teacher = client.post("/api/v1/timetable/teachers", json=teacher_payload, headers=headers)
        assert teacher.status_code == 201
        assert teacher.json()["short_code"] == "TEACH-A"
        assert teacher.json()["availability"] == availability
        assert client.post("/api/v1/timetable/teachers", json=teacher_payload, headers=headers).status_code == 409
        invalid_availability = {**availability, "MON": ["P1", "LUNCH"]}
        assert (
            client.post(
                "/api/v1/timetable/teachers",
                json={**teacher_payload, "short_code": "TEACH-B", "availability": invalid_availability},
                headers=headers,
            ).status_code
            == 422
        )

        subject = client.post("/api/v1/timetable/subjects", json={"code": "math", "name": "Mathematics"}, headers=headers)
        instructional_class = client.post(
            "/api/v1/timetable/classes",
            json={"code": "A4A", "name": "A4 A", "reporting_order": 10},
            headers=headers,
        )
        cluster = client.post("/api/v1/timetable/clusters", json={"code": "NORTH", "name": "North Cluster"}, headers=headers)
        assert subject.status_code == instructional_class.status_code == cluster.status_code == 201
        class_id = instructional_class.json()["id"]
        cluster_id = cluster.json()["id"]
        member_payload = {"instructional_class_id": class_id}
        assert client.post(f"/api/v1/timetable/clusters/{cluster_id}/classes", json=member_payload, headers=headers).status_code == 201
        assert client.post(f"/api/v1/timetable/clusters/{cluster_id}/classes", json=member_payload, headers=headers).status_code == 409

        resolved = client.get(f"/api/v1/timetable/classes/{class_id}/periods", headers=headers)
        assert resolved.status_code == 200
        assert [period["slot_code"] for period in resolved.json()] == ["P1", "P2", "LUNCH", "P3", "P4"]
        lunch = resolved.json()[2]
        assert lunch["is_schedulable"] is False
        assert lunch["display_order"] == 3
        assert client.patch(f"/api/v1/timetable/periods/{lunch['id']}", {"label": "Teaching Period"}, headers=headers).status_code == 422

        cluster_period = {
            "scope": "CLUSTER",
            "target_id": cluster_id,
            "slot_code": "P1",
            "label": "Morning block",
            "starts_at": "08:00",
            "ends_at": "08:45",
        }
        assert client.post("/api/v1/timetable/periods", json=cluster_period, headers=headers).status_code == 201
        assert client.post("/api/v1/timetable/periods", json=cluster_period, headers=headers).status_code == 409
        assert client.get(f"/api/v1/timetable/classes/{class_id}/periods", headers=headers).json()[0]["label"] == "Morning block"

        class_period = {
            "scope": "CLASS",
            "target_id": class_id,
            "slot_code": "P1",
            "label": "A4 A first period",
            "starts_at": "08:15",
            "ends_at": "09:00",
        }
        assert client.post("/api/v1/timetable/periods", json=class_period, headers=headers).status_code == 201
        assert client.get(f"/api/v1/timetable/classes/{class_id}/periods", headers=headers).json()[0]["label"] == "A4 A first period"
        overlapping_period = {
            "scope": "CLASS",
            "target_id": class_id,
            "slot_code": "P2",
            "label": "Overlapping period",
            "starts_at": "08:45",
            "ends_at": "09:30",
        }
        assert client.post("/api/v1/timetable/periods", json=overlapping_period, headers=headers).status_code == 409
        assert (
            client.post(
                "/api/v1/timetable/periods",
                json={**class_period, "slot_code": "LUNCH", "label": "Teaching period", "starts_at": "12:00", "ends_at": "12:30"},
                headers=headers,
            ).status_code
            == 422
        )

        actions = {event["action"] for event in client.get("/api/v1/reports/audit", headers=headers).json()}
        assert {
            "timetable.teacher.created",
            "timetable.subject.created",
            "timetable.class.created",
            "timetable.cluster.created",
            "timetable.cluster.class_added",
            "timetable.period.created",
        } <= actions
