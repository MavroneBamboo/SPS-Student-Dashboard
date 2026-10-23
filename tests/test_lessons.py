import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, engine
from app.main import app
from app.models import AuditEvent, LessonRequirement, User
from app.security import hash_password

BASE = "/api/v1/timetable"


@pytest.fixture
def lesson_context():
    suffix = uuid4().hex[:10]
    password = "lesson-fixture-password"
    password_hash = hash_password(password)
    with TestClient(app) as client:
        headers = {}
        for key, role in (("admin", "IT Administrator"), ("operator", "Operator"), ("executive", "Executive"), ("superuser", "Superuser")):
            username = f"lesson-{key}-{suffix}"
            with SessionLocal() as db:
                db.add(User(username=username, password_hash=password_hash, role=role, must_change_password=False, is_active=True))
                db.commit()
            login = client.post("/api/v1/auth/login", json={"username": username, "password": password})
            assert login.status_code == 200
            headers[key] = {"Authorization": f"Bearer {login.json()['access_token']}"}
        references = {}
        for path, payload, key in (
            ("teachers", {"short_code": f"T{suffix}", "full_name": "Lesson Test Teacher"}, "teacher_id"),
            ("subjects", {"code": f"S{suffix}", "name": "Lesson Test Subject"}, "subject_id"),
            ("classes", {"code": f"C{suffix}", "name": "Lesson Test Class"}, "instructional_class_id"),
        ):
            created = client.post(f"{BASE}/{path}", json=payload, headers=headers["admin"])
            assert created.status_code == 201, created.text
            references[key] = created.json()["id"]
        yield client, headers, {"academic_year": "2026", "weekly_count": 4, "block_length": 2, **references}


def test_lesson_lifecycle_permissions_and_concurrent_edits(lesson_context):
    client, headers, payload = lesson_context
    for role in ("executive", "superuser"):
        assert client.post(f"{BASE}/lessons", json=payload, headers=headers[role]).status_code == 403
        assert client.get(f"{BASE}/lessons", headers=headers[role]).status_code == 403
    assert client.get(f"{BASE}/lessons").status_code == 401
    created = client.post(f"{BASE}/lessons", json=payload, headers=headers["operator"])
    assert created.status_code == 201, created.text
    lesson_id = created.json()["id"]
    assert created.json()["version"] == 1
    assert client.post(f"{BASE}/lessons", json=payload, headers=headers["admin"]).status_code == 409
    assert client.post(f"{BASE}/lessons", json={**payload, "academic_year": "2027"}, headers=headers["operator"]).status_code == 201
    assert client.post(f"{BASE}/lessons", json={**payload, "academic_year": " 2026 "}, headers=headers["operator"]).status_code == 409
    assert (
        client.put(
            f"{BASE}/lessons/{lesson_id}",
            json={**payload, "academic_year": "2027", "expected_version": 1, "is_active": True},
            headers=headers["operator"],
        ).status_code
        == 409
    )

    changed = client.put(
        f"{BASE}/lessons/{lesson_id}",
        json={**payload, "weekly_count": 6, "expected_version": 1, "is_active": True},
        headers=headers["operator"],
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["version"] == 2
    assert (
        client.put(
            f"{BASE}/lessons/{lesson_id}",
            json={**payload, "expected_version": 1, "is_active": True},
            headers=headers["operator"],
        ).status_code
        == 409
    )
    assert client.delete(f"{BASE}/lessons/{lesson_id}?expected_version=1", headers=headers["operator"]).status_code == 409
    archived = client.delete(f"{BASE}/lessons/{lesson_id}?expected_version=2", headers=headers["operator"])
    assert archived.status_code == 200
    assert archived.json()["is_active"] is False
    assert archived.json()["version"] == 3
    filters = {"academic_year": "2026", "instructional_class_id": payload["instructional_class_id"]}
    assert client.get(f"{BASE}/lessons", params=filters, headers=headers["operator"]).json() == []
    archived_list = client.get(f"{BASE}/lessons", params={**filters, "include_inactive": True}, headers=headers["admin"]).json()
    assert [row["id"] for row in archived_list] == [lesson_id]
    assert client.post(f"{BASE}/lessons", json=payload, headers=headers["operator"]).status_code == 409
    restored = client.put(
        f"{BASE}/lessons/{lesson_id}",
        json={**payload, "expected_version": 3, "is_active": True},
        headers=headers["admin"],
    )
    assert restored.status_code == 200
    assert restored.json()["version"] == 4

    barrier = Barrier(2)

    def save(count):
        barrier.wait(timeout=10)
        return client.put(
            f"{BASE}/lessons/{lesson_id}",
            json={**payload, "weekly_count": count, "expected_version": 4, "is_active": True},
            headers=headers["operator"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(save, (8, 10)))
    assert sorted(response.status_code for response in responses) == [200, 409]
    final = client.get(f"{BASE}/lessons/{lesson_id}", headers=headers["operator"]).json()
    assert final["version"] == 5
    assert final["weekly_count"] in (8, 10)
    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "lesson_requirement", AuditEvent.entity_id == str(lesson_id))
        ).all()
        assert len(events) == 5  # create, update, archive, restore, one winning concurrent update
        assert {event.action for event in events} == {"timetable.lesson.created", "timetable.lesson.updated", "timetable.lesson.archived"}
        assert sum(json.loads(event.details_json).get("before", {}).get("version") == 4 for event in events) == 1


def test_lesson_rejects_bad_counts_missing_and_inactive_references(lesson_context):
    client, headers, payload = lesson_context
    for changes in (
        {"weekly_count": 0},
        {"weekly_count": 21},
        {"block_length": 0},
        {"block_length": 5},
        {"teacher_id": -1},
        {"academic_year": "  "},
        {"teacher_name": "uncontrolled reference"},
        {"teacher_id": 2147483647},
        {"subject_id": 2147483647},
        {"instructional_class_id": 2147483647},
    ):
        response = client.post(f"{BASE}/lessons", json={**payload, **changes}, headers=headers["operator"])
        assert response.status_code == 422, response.text
    mixed_blocks = client.post(f"{BASE}/lessons", json={**payload, "weekly_count": 3}, headers=headers["operator"])
    assert mixed_blocks.status_code == 201, mixed_blocks.text
    for path, resource_payload, key in (
        ("teachers", {"short_code": f"I{uuid4().hex[:12]}", "full_name": "Inactive Teacher"}, "teacher_id"),
        ("subjects", {"code": f"I{uuid4().hex[:12]}", "name": "Inactive Subject"}, "subject_id"),
        ("classes", {"code": f"I{uuid4().hex[:12]}", "name": "Inactive Class"}, "instructional_class_id"),
    ):
        resource = client.post(f"{BASE}/{path}", json={**resource_payload, "is_active": False}, headers=headers["admin"])
        assert resource.status_code == 201
        rejected = client.post(f"{BASE}/lessons", json={**payload, key: resource.json()["id"]}, headers=headers["operator"])
        assert rejected.status_code == 422
        assert "inactive" in rejected.json()["detail"]


def test_lesson_blocks_respect_lunch_availability_and_custom_time_gaps(lesson_context):
    client, headers, payload = lesson_context

    def teacher_with_availability(monday):
        availability = {day: [] for day in ("MON", "TUE", "WED", "THU", "FRI")}
        availability["MON"] = monday
        created = client.post(
            f"{BASE}/teachers",
            json={"short_code": f"A{uuid4().hex[:12]}", "full_name": "Limited Teacher", "availability": availability},
            headers=headers["admin"],
        )
        assert created.status_code == 201
        return created.json()["id"]

    split_teacher = teacher_with_availability(["P2", "P3"])
    rejected = client.post(f"{BASE}/lessons", json={**payload, "teacher_id": split_teacher, "weekly_count": 2}, headers=headers["operator"])
    assert rejected.status_code == 422  # cannot join the teaching periods across lunch
    singles = client.post(
        f"{BASE}/lessons", json={**payload, "teacher_id": split_teacher, "weekly_count": 2, "block_length": 1}, headers=headers["operator"]
    )
    assert singles.status_code == 201
    morning_teacher = teacher_with_availability(["P1", "P2"])
    morning = {**payload, "teacher_id": morning_teacher, "weekly_count": 2}
    assert client.post(f"{BASE}/lessons", json={**morning, "weekly_count": 4}, headers=headers["operator"]).status_code == 422
    morning_lesson = client.post(f"{BASE}/lessons", json=morning, headers=headers["operator"])
    assert morning_lesson.status_code == 201
    period_payload = {
        "scope": "CLASS",
        "target_id": payload["instructional_class_id"],
        "slot_code": "P1",
        "label": "Early period",
        "starts_at": "08:30",
        "ends_at": "09:30",
    }
    blocked_change = client.post(f"{BASE}/periods", json=period_payload, headers=headers["admin"])
    assert blocked_change.status_code == 409  # prevent invalidating the existing active double lesson
    assert client.delete(f"{BASE}/lessons/{morning_lesson.json()['id']}?expected_version=1", headers=headers["operator"]).status_code == 200
    override = client.post(
        f"{BASE}/periods",
        json=period_payload,
        headers=headers["admin"],
    )
    assert override.status_code == 201
    assert (
        client.post(f"{BASE}/lessons", json={**morning, "academic_year": "2028"}, headers=headers["operator"]).status_code == 422
    )  # the configured gap before P2 also breaks a block


def test_postgresql_enforces_lesson_uniqueness_foreign_keys_and_numeric_constraints(lesson_context):
    if engine.dialect.name != "postgresql":
        pytest.skip("Production database constraint proof requires PostgreSQL")
    client, headers, payload = lesson_context
    assert client.post(f"{BASE}/lessons", json=payload, headers=headers["operator"]).status_code == 201
    for changes in (
        {},
        {"academic_year": "DB1", "teacher_id": 2147483647},
        {"academic_year": "DB2", "weekly_count": 0},
        {"academic_year": "DB3", "block_length": 5},
        {"academic_year": "DB4", "version": 0},
    ):
        with SessionLocal() as db:
            invalid = LessonRequirement(**{**payload, "is_active": True, "version": 1, "created_by": 0, "updated_by": 0, **changes})
            db.add(invalid)
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()


def test_concurrent_period_change_and_lesson_creation_cannot_commit_an_invalid_pair(lesson_context):
    if engine.dialect.name != "postgresql":
        pytest.skip("Cross-process configuration serialization requires production PostgreSQL")
    client, headers, payload = lesson_context
    teacher = client.post(
        f"{BASE}/teachers",
        json={
            "short_code": f"R{uuid4().hex[:12]}",
            "full_name": "Concurrent Test Teacher",
            "availability": {"MON": ["P1", "P2"], "TUE": [], "WED": [], "THU": [], "FRI": []},
        },
        headers=headers["admin"],
    )
    assert teacher.status_code == 201
    barrier = Barrier(2)

    def write(kind):
        barrier.wait(timeout=10)
        if kind == "lesson":
            return client.post(
                f"{BASE}/lessons", json={**payload, "teacher_id": teacher.json()["id"], "weekly_count": 2}, headers=headers["operator"]
            )
        return client.post(
            f"{BASE}/periods",
            json={
                "scope": "CLASS",
                "target_id": payload["instructional_class_id"],
                "slot_code": "P1",
                "label": "Short period",
                "starts_at": "08:30",
                "ends_at": "09:30",
            },
            headers=headers["admin"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(write, ("lesson", "period")))
    statuses = [result.status_code for result in results]
    assert statuses in ([201, 409], [422, 201]), [result.text for result in results]
