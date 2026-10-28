"""Verify operational boundaries and complete Superuser access."""

from uuid import uuid4


def test_superuser_and_operator_operational_access(lesson_context):
    client, headers, _ = lesson_context
    identifier = f"ROLE-{uuid4().hex[:12]}"
    class_name = f"ROLE CLASS {uuid4().hex[:8]}"
    student = client.post(
        "/api/v1/students",
        json={"pris_no": identifier, "name": "Restricted Student", "class_name": class_name, "category": "OP"},
        headers=headers["operator"],
    )
    assert student.status_code == 201
    student_id = student.json()["id"]
    session = client.post(
        "/api/v1/attendance/sessions",
        json={"session_date": "2026-10-26", "session_type": "MORNING", "class_name": class_name, "expected_count": 1},
        headers=headers["operator"],
    )
    assert session.status_code == 201
    session_id = session.json()["id"]
    paths = (
        "/api/v1/students",
        f"/api/v1/students/{student_id}",
        f"/api/v1/students/{student_id}/status-history",
        "/api/v1/attendance/sessions",
        f"/api/v1/attendance/sessions/{session_id}",
        f"/api/v1/attendance/sessions/{session_id}/records",
    )

    for role in ("admin", "executive"):
        for path in paths:
            assert client.get(path, headers=headers[role]).status_code == 403, (role, path)
        assert (
            client.post(
                "/api/v1/students",
                json={"pris_no": f"{identifier}-{role}", "name": "Denied", "class_name": class_name, "category": "OP"},
                headers=headers[role],
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/attendance/sessions",
                json={"session_date": "2026-10-27", "session_type": "MORNING", "class_name": class_name, "expected_count": 1},
                headers=headers[role],
            ).status_code
            == 403
        )

    for role in ("operator", "superuser"):
        for path in paths:
            assert client.get(path, headers=headers[role]).status_code == 200, (role, path)

    created = client.post(
        "/api/v1/students",
        json={"pris_no": f"{identifier}-SUPERUSER", "name": "Superuser Student", "class_name": class_name, "category": "OP"},
        headers=headers["superuser"],
    )
    assert created.status_code == 201
    created_session = client.post(
        "/api/v1/attendance/sessions",
        json={"session_date": "2026-10-27", "session_type": "MORNING", "class_name": class_name, "expected_count": 1},
        headers=headers["superuser"],
    )
    assert created_session.status_code == 201

    for role in ("operator", "executive", "superuser"):
        assert client.get("/api/v1/reports/dashboard", headers=headers[role]).status_code == 200
        assert client.get("/api/v1/reports/attendance.csv", headers=headers[role]).status_code == 200
    for role in ("admin", "superuser"):
        assert client.get("/api/v1/reports/audit", headers=headers[role]).status_code == 200
    for role in ("operator", "executive"):
        assert client.get("/api/v1/reports/audit", headers=headers[role]).status_code == 403
    for path in ("/api/v1/reports/dashboard", "/api/v1/reports/attendance.csv"):
        assert client.get(path, headers=headers["admin"]).status_code == 403
