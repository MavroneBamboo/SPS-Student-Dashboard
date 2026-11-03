import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.crypto import decrypt_sensitive
from app.db import SessionLocal
from app.models import AttendanceRecord, AttendanceRosterEntry, AttendanceSession, AuditEvent

BASE = "/api/v1/attendance"


@pytest.fixture
def attendance_context(lesson_context):
    client, headers, _ = lesson_context
    class_name = "ATT-" + uuid4().hex[:10]
    students = []
    for index in range(2):
        response = client.post(
            "/api/v1/students",
            json={
                "pris_no": f"{class_name}-{index}",
                "name": f"Attendance Student {index}",
                "class_name": class_name,
                "class_effective_date": "2026-10-01",
                "category": "OP",
                "status": "ACTIVE",
                "status_effective": "2026-10-01",
            },
            headers=headers["operator"],
        )
        assert response.status_code == 201
        students.append(response.json())
    return (
        client,
        headers,
        {"session_date": "2026-10-26", "session_type": "MORNING", "class_name": class_name, "expected_count": 2},
        students,
    )


def _session(ctx, **changes):
    client, headers, payload, _ = ctx
    response = client.post(BASE + "/sessions", json={**payload, **changes}, headers=headers["operator"])
    assert response.status_code == 201, response.text
    return response.json()


def _record(ctx, session, index=0, status="PRESENT"):
    client, headers, _, students = ctx
    return client.post(
        f"{BASE}/sessions/{session['id']}/records",
        json={"pris_no": students[index]["pris_no"], "attendance_status": status, "expected_session_version": session["version"]},
        headers=headers["operator"],
    )


def test_attendance_full_lifecycle_missing_review_correction_and_close(attendance_context):
    ctx = attendance_context
    client, headers, _, students = ctx
    session = _session(ctx)
    path = f"{BASE}/sessions/{session['id']}"
    record = _record(ctx, session)
    assert record.status_code == 201
    grid = client.get(path, headers=headers["operator"]).json()
    assert grid["missing"] == 1 and grid["session"]["version"] == 2
    assert client.post(path + "/close", json={"expected_version": 2}, headers=headers["operator"]).status_code == 409
    assert _record(ctx, grid["session"]).status_code == 409
    missing = _record(ctx, grid["session"], index=1, status="MISSING")
    assert missing.status_code == 201
    grid = client.get(path, headers=headers["operator"]).json()
    assert grid["missing"] == 0 and grid["marked_missing"] == 1
    dashboard = client.get("/api/v1/reports/dashboard", params={"class_name": session["class_name"]}, headers=headers["operator"]).json()
    assert dashboard["attendance"]["missing"] == 1
    assert client.post(path + "/close", json={"expected_version": 3}, headers=headers["operator"]).status_code == 409
    corrected = client.patch(
        f"{BASE}/records/{missing.json()['id']}",
        json={
            "pris_no": students[1]["pris_no"],
            "attendance_status": "ABSENT",
            "correction_reason": "Verified paper register",
            "expected_version": 1,
            "expected_session_version": 3,
        },
        headers=headers["operator"],
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["version"] == 2 and corrected.json()["session_version"] == 4
    closed = client.post(path + "/close", json={"expected_version": 4}, headers=headers["operator"])
    assert closed.status_code == 200 and closed.json()["status"] == "CLOSED" and closed.json()["version"] == 5
    assert _record(ctx, closed.json()).status_code == 409
    assert client.post(path + "/close", json={"expected_version": 5}, headers=headers["operator"]).status_code == 409
    with SessionLocal() as db:
        event = db.scalars(
            select(AuditEvent).where(AuditEvent.action == "attendance.record.corrected", AuditEvent.entity_id == str(missing.json()["id"]))
        ).one()
        detail = json.loads(event.details_json)
        assert detail["before"]["attendance_status"] == "MISSING" and detail["after"]["attendance_status"] == "ABSENT"


def test_session_roster_snapshot_survives_student_transfer_and_rejects_later_enrollment(attendance_context):
    ctx = attendance_context
    client, headers, payload, students = ctx
    session = _session(ctx)
    detail_url = f"{BASE}/sessions/{session['id']}"
    detail = client.get(detail_url, headers=headers["operator"]).json()
    assert detail["roster_snapshot_complete"] is True
    assert detail["roster_count"] == 2
    assert {entry["pris_no"] for entry in detail["roster"]} == {student["pris_no"] for student in students}
    with SessionLocal() as db:
        stored = db.scalar(
            select(AttendanceRosterEntry).where(
                AttendanceRosterEntry.session_id == session["id"],
                AttendanceRosterEntry.student_id == students[0]["id"],
            )
        )
        assert stored.student_name_encrypted != "Attendance Student 0"
        assert decrypt_sensitive(stored.student_name_encrypted) == "Attendance Student 0"

    transferred = client.patch(
        f"/api/v1/students/{students[0]['id']}",
        json={
            "expected_version": students[0]["version"],
            "name": "Transferred After Session",
            "class_name": "Another Class",
            "class_effective_date": "2026-10-27",
            "status": "INACTIVE",
            "status_effective": "2026-10-27",
        },
        headers=headers["operator"],
    )
    assert transferred.status_code == 200
    added = client.post(
        "/api/v1/students",
        json={"pris_no": f"{payload['class_name']}-LATE", "name": "Later Student", "class_name": payload["class_name"], "category": "OP"},
        headers=headers["operator"],
    )
    assert added.status_code == 201

    recorded = client.post(
        f"{BASE}/sessions/{session['id']}/records",
        json={"pris_no": students[0]["pris_no"], "attendance_status": "ABSENT", "expected_session_version": session["version"]},
        headers=headers["operator"],
    )
    assert recorded.status_code == 201
    assert recorded.json()["student_name"] == "Attendance Student 0"
    assert (
        client.post(
            f"{BASE}/sessions/{session['id']}/records",
            json={"pris_no": added.json()["pris_no"], "attendance_status": "PRESENT", "expected_session_version": 2},
            headers=headers["operator"],
        ).status_code
        == 422
    )
    final = client.get(detail_url, headers=headers["operator"]).json()
    frozen = next(entry for entry in final["roster"] if entry["student_id"] == students[0]["id"])
    assert frozen["student_name"] == "Attendance Student 0"
    assert frozen["student_status"] == "ACTIVE"
    assert frozen["attendance_status"] == "ABSENT"


def test_backdated_attendance_uses_class_and_status_as_of_session_date(lesson_context):
    client, headers, _ = lesson_context
    original_class = f"HISTORY-{uuid4().hex[:8]}"
    moved_class = f"{original_class}-MOVED"
    profiles = []
    for index in range(3):
        response = client.post(
            "/api/v1/students",
            json={
                "pris_no": f"{original_class}-{index}",
                "name": f"Historical roster student {index}",
                "class_name": original_class,
                "class_effective_date": "2026-10-01",
                "category": "OP",
                "status": "ACTIVE",
                "status_effective": "2026-10-01",
            },
            headers=headers["operator"],
        )
        assert response.status_code == 201, response.text
        profiles.append(response.json())

    inactive = client.patch(
        f"/api/v1/students/{profiles[1]['id']}",
        json={"expected_version": profiles[1]["version"], "status": "INACTIVE", "status_effective": "2026-10-27"},
        headers=headers["operator"],
    )
    assert inactive.status_code == 200, inactive.text
    changed = client.patch(
        f"/api/v1/students/{profiles[0]['id']}",
        json={"expected_version": profiles[0]["version"], "class_name": moved_class, "class_effective_date": "2026-10-27"},
        headers=headers["operator"],
    )
    assert changed.status_code == 200, changed.text
    history = client.get(f"/api/v1/students/{profiles[0]['id']}/class-history", headers=headers["operator"])
    assert history.status_code == 200
    assert [(entry["effective_date"], entry["class_name"]) for entry in history.json()] == [
        ("2026-10-01", original_class),
        ("2026-10-27", moved_class),
    ]

    for class_name, expected_pris_no in ((original_class, profiles[2]["pris_no"]), (moved_class, profiles[0]["pris_no"])):
        created = client.post(
            "/api/v1/attendance/sessions",
            json={"session_date": "2026-10-28", "session_type": "MORNING", "class_name": class_name, "expected_count": 1},
            headers=headers["operator"],
        )
        assert created.status_code == 201, created.text
        roster = client.get(f"/api/v1/attendance/sessions/{created.json()['id']}", headers=headers["operator"]).json()["roster"]
        assert [entry["pris_no"] for entry in roster] == [expected_pris_no]


def test_attendance_does_not_guess_roster_before_class_history_begins(lesson_context):
    client, headers, _ = lesson_context
    class_name = f"NO-HISTORY-{uuid4().hex[:8]}"
    created = client.post(
        "/api/v1/students",
        json={"pris_no": f"{class_name}-1", "name": "No historical membership", "class_name": class_name, "category": "OP"},
        headers=headers["operator"],
    )
    assert created.status_code == 201
    session = client.post(
        "/api/v1/attendance/sessions",
        json={"session_date": "2026-11-02", "session_type": "MORNING", "class_name": class_name, "expected_count": 1},
        headers=headers["operator"],
    )
    assert session.status_code == 422
    assert "effective class assignment" in session.json()["detail"]


def test_duplicate_session_race_and_database_constraint(attendance_context):
    client, headers, payload, _ = attendance_context
    barrier = Barrier(2)

    def create(_):
        barrier.wait(timeout=10)
        return client.post(BASE + "/sessions", json=payload, headers=headers["operator"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(create, range(2)))
    assert sorted(response.status_code for response in responses) == [201, 409]
    winner = next(response.json() for response in responses if response.status_code == 201)
    with SessionLocal() as db:
        db.add(AttendanceSession(**{**payload, "session_date": date.fromisoformat(payload["session_date"])}, created_by=1, status="OPEN"))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    assert (
        client.get(BASE + "/sessions", params={"class_name": payload["class_name"], "limit": 1}, headers=headers["operator"]).json()[0][
            "id"
        ]
        == winner["id"]
    )
    assert (
        client.post(BASE + "/sessions", json={**payload, "class_name": "Nonexistent class"}, headers=headers["operator"]).status_code == 422
    )


def test_record_and_incomplete_close_race_has_one_winner(attendance_context):
    ctx = attendance_context
    client, headers, _, _ = ctx
    session = _session(ctx)
    barrier = Barrier(2)

    def execute(action):
        barrier.wait(timeout=10)
        if action == "record":
            return _record(ctx, session)
        return client.post(
            f"{BASE}/sessions/{session['id']}/close",
            json={"expected_version": 1, "allow_incomplete": True, "reason": "Register unavailable at cutoff"},
            headers=headers["operator"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(execute, ("record", "close")))
    assert sum(response.status_code == 409 for response in responses) == 1
    grid = client.get(f"{BASE}/sessions/{session['id']}", headers=headers["operator"]).json()
    assert grid["session"]["version"] == 2
    assert len(grid["records"]) == (1 if responses[0].status_code == 201 else 0)
    assert grid["session"]["status"] == ("OPEN" if grid["records"] else "CLOSED")


def test_expected_count_adjustment_is_versioned_reasoned_and_not_below_recorded(attendance_context):
    ctx = attendance_context
    client, headers, _, _ = ctx
    session = _session(ctx, expected_count=1)
    path = f"{BASE}/sessions/{session['id']}"
    assert _record(ctx, session).status_code == 201
    session = client.get(path, headers=headers["operator"]).json()["session"]
    assert _record(ctx, session, index=1).status_code == 409
    adjusted = client.patch(
        path, json={"expected_version": 2, "expected_count": 2, "reason": "Additional student confirmed"}, headers=headers["operator"]
    )
    assert adjusted.status_code == 200 and adjusted.json()["version"] == 3
    assert _record(ctx, adjusted.json(), index=1).status_code == 201
    assert (
        client.patch(
            path,
            json={"expected_version": 4, "expected_count": 1, "reason": "Must not hide recorded attendance"},
            headers=headers["operator"],
        ).status_code
        == 409
    )
    assert (
        client.patch(path, json={"expected_version": 4, "expected_count": 3, "reason": "   "}, headers=headers["operator"]).status_code
        == 422
    )
    assert (
        client.post(path + "/close", json={"expected_version": 4, "allow_incomplete": True}, headers=headers["operator"]).status_code == 422
    )
    assert client.post(path + "/close", json={"expected_version": 4}, headers=headers["operator"]).status_code == 200


def test_correction_concurrency_identity_permissions_and_stale_versions(attendance_context):
    ctx = attendance_context
    client, headers, _, students = ctx
    session = _session(ctx)
    record = _record(ctx, session).json()
    path = f"{BASE}/records/{record['id']}"
    payload = {
        "pris_no": students[0]["pris_no"],
        "attendance_status": "ABSENT",
        "correction_reason": "Confirmed by register",
        "expected_version": 1,
        "expected_session_version": 2,
    }
    assert client.patch(path, json={**payload, "pris_no": students[1]["pris_no"]}, headers=headers["operator"]).status_code == 422
    assert client.patch(path, json={**payload, "correction_reason": "   "}, headers=headers["operator"]).status_code == 422
    assert client.patch(path, json={**payload, "expected_version": 5}, headers=headers["operator"]).status_code == 409
    barrier = Barrier(2)

    def correct(mark):
        barrier.wait(timeout=10)
        return client.patch(path, json={**payload, "attendance_status": mark}, headers=headers["operator"])

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(correct, ("ABSENT", "LATE")))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert client.get(f"{BASE}/sessions/{session['id']}/records", headers=headers["executive"]).status_code == 403
    assert client.get(BASE + "/sessions", headers=headers["executive"]).status_code == 403
    assert client.get(BASE + "/sessions").status_code == 401
    assert client.get(BASE + "/sessions?date_from=2026-10-26&date_to=2026-10-01", headers=headers["operator"]).status_code == 422


def test_attendance_audit_failure_rolls_back_session_record_and_revision(attendance_context, monkeypatch):
    from app.routes import attendance

    ctx = attendance_context
    client, headers, _, _ = ctx
    session = _session(ctx)
    original = attendance.record_event

    def fail(db, *args, **kwargs):
        original(db, *args, **kwargs)
        raise RuntimeError("Injected attendance audit failure")

    monkeypatch.setattr(attendance, "record_event", fail)
    with pytest.raises(RuntimeError, match="Injected attendance audit failure"):
        _record(ctx, session)
    grid = client.get(f"{BASE}/sessions/{session['id']}", headers=headers["operator"]).json()
    assert grid["session"]["version"] == 1 and grid["records"] == []
    with SessionLocal() as db:
        assert not db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id == session["id"])).all()
