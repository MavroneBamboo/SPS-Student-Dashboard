import json
from concurrent.futures import ThreadPoolExecutor
from datetime import time
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.db import SessionLocal, engine
from app.models import AuditEvent, Teacher, TimetablePlacement, TimetableSlot, TimetableVersion, TimetableVersionClass

BASE = "/api/v1/timetable"


@pytest.fixture
def timetable_context(lesson_context):
    client, headers, lesson = lesson_context
    lesson = {**lesson, "academic_year": f"PLAN-{lesson['instructional_class_id']}"}
    requirement = client.post(f"{BASE}/lessons", json=lesson, headers=headers["operator"])
    assert requirement.status_code == 201
    rule_payload = {
        "academic_year": lesson["academic_year"],
        "target_type": "CLASS",
        "target_id": lesson["instructional_class_id"],
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "rule": {},
    }
    rule = client.post(f"{BASE}/rules", json=rule_payload, headers=headers["admin"])
    assert rule.status_code == 201
    return {
        "client": client,
        "headers": headers,
        "lesson": lesson,
        "lesson_id": requirement.json()["id"],
        "rule": rule_payload,
        "rule_id": rule.json()["id"],
        "draft": {
            "name": "Operational week",
            "academic_year": lesson["academic_year"],
            "week_start": "2026-10-19",
            "class_ids": [lesson["instructional_class_id"]],
        },
    }


def _draft(ctx, **changes):
    response = ctx["client"].post(f"{BASE}/versions", json={**ctx["draft"], **changes}, headers=ctx["headers"]["operator"])
    assert response.status_code == 201, response.text
    return response.json()


def _body(ctx, version, **changes):
    return {
        "expected_revision": version["revision"],
        "lesson_requirement_id": ctx["lesson_id"],
        "weekday": "MON",
        "start_period": "P1",
        "period_count": 2,
        **changes,
    }


def _place(ctx, version, **changes):
    return ctx["client"].post(
        f"{BASE}/versions/{version['id']}/placements", json=_body(ctx, version, **changes), headers=ctx["headers"]["operator"]
    )


def _single_requirement(ctx, count=2):
    response = ctx["client"].put(
        f"{BASE}/lessons/{ctx['lesson_id']}",
        json={**ctx["lesson"], "weekly_count": count, "block_length": 1, "expected_version": 1, "is_active": True},
        headers=ctx["headers"]["operator"],
    )
    assert response.status_code == 200


def test_draft_amend_lock_swap_remove_approve_and_snapshot_history(timetable_context):
    ctx = timetable_context
    client, headers = ctx["client"], ctx["headers"]
    version = _draft(ctx)
    path = f"{BASE}/versions/{version['id']}"
    assert version["pending"][0]["remaining_periods"] == 4
    assert client.get(path, headers=headers["executive"]).status_code == 404
    assert all(row["id"] != version["id"] for row in client.get(f"{BASE}/versions", headers=headers["executive"]).json())
    assert client.get(path, headers=headers["superuser"]).status_code == 403
    assert client.post(path + "/approve", json={"expected_revision": 1}, headers=headers["operator"]).status_code == 403
    assert client.post(path + "/approve", json={"expected_revision": 1}, headers=headers["admin"]).status_code == 409
    placed = _place(ctx, version)
    assert placed.status_code == 201, placed.text
    version = placed.json()
    first_id = version["placements"][0]["id"]
    assert [slot["slot_code"] for slot in version["placements"][0]["slots"]] == ["P1", "P2"]
    moved = client.put(
        path + f"/placements/{first_id}", json=_body(ctx, version, weekday="TUE", start_period="P3"), headers=headers["operator"]
    )
    assert moved.status_code == 200, moved.text
    version = moved.json()
    assert version["revision"] == 3
    assert all(slot["weekday"] == "TUE" for slot in version["placements"][0]["slots"])
    assert _place(ctx, version, weekday="TUE", start_period="P3").status_code == 409
    assert _place(ctx, version, expected_revision=1).status_code == 409
    added = _place(ctx, version, weekday="THU")
    assert added.status_code == 201
    version = added.json()
    second_id = next(block["id"] for block in version["placements"] if block["id"] != first_id)
    locked = client.patch(
        path + f"/placements/{first_id}/lock", json={"expected_revision": 4, "is_locked": True}, headers=headers["operator"]
    )
    assert locked.status_code == 200
    assert client.delete(path + f"/placements/{first_id}?expected_revision=5", headers=headers["operator"]).status_code == 409
    assert client.put(path + f"/placements/{first_id}", json=_body(ctx, locked.json()), headers=headers["operator"]).status_code == 409
    swap_payload = {"expected_revision": 5, "first_placement_id": first_id, "second_placement_id": second_id}
    assert client.post(path + "/swap", json=swap_payload, headers=headers["operator"]).status_code == 409
    unlocked = client.patch(
        path + f"/placements/{first_id}/lock", json={"expected_revision": 5, "is_locked": False}, headers=headers["operator"]
    )
    assert unlocked.status_code == 200
    swapped = client.post(path + "/swap", json={**swap_payload, "expected_revision": 6}, headers=headers["operator"])
    assert swapped.status_code == 200, swapped.text
    version = swapped.json()
    blocks = {block["id"]: block for block in version["placements"]}
    assert (blocks[first_id]["weekday"], blocks[first_id]["start_period"]) == ("THU", "P1")
    assert (blocks[second_id]["weekday"], blocks[second_id]["start_period"]) == ("TUE", "P3")
    removed = client.delete(path + f"/placements/{first_id}?expected_revision=7", headers=headers["operator"])
    assert removed.status_code == 200
    assert removed.json()["pending"][0]["remaining_periods"] == 2
    replaced = _place(ctx, removed.json(), weekday="THU")
    assert replaced.status_code == 201
    version = replaced.json()
    assert not version["pending"]
    assert version["revision"] == 9
    approved = client.post(path + "/approve", json={"expected_revision": 9}, headers=headers["admin"])
    assert approved.status_code == 200, approved.text
    version = approved.json()
    assert version["status"] == "APPROVED" and version["revision"] == 10
    assert client.get(path, headers=headers["executive"]).json() == version
    assert _place(ctx, version).status_code == 409
    old_name = version["snapshot"]["teachers"][str(ctx["lesson"]["teacher_id"])]["full_name"]
    with SessionLocal() as db:
        db.get(Teacher, ctx["lesson"]["teacher_id"]).full_name = "Changed live profile"
        db.commit()
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "timetable_version", AuditEvent.entity_id == str(version["id"]))
        ).all()
        assert len(events) == 10
        additions = [event for event in events if event.action == "timetable.lesson.added"]
        assert all(json.loads(event.details_json)["after"][0]["id"] > 0 for event in additions)
    assert (
        client.get(path, headers=headers["executive"]).json()["snapshot"]["teachers"][str(ctx["lesson"]["teacher_id"])]["full_name"]
        == old_name
    )
    replacement = _draft(ctx, name="Replacement version")
    assert replacement["id"] != version["id"] and replacement["placements"] == []
    assert replacement["snapshot"]["teachers"][str(ctx["lesson"]["teacher_id"])]["full_name"] == "Changed live profile"
    assert (
        client.put(
            f"{BASE}/versions/{replacement['id']}/placements/{second_id}", json=_body(ctx, replacement), headers=headers["operator"]
        ).status_code
        == 404
    )


def test_rule_limits_availability_lunch_and_block_pattern_are_enforced(timetable_context):
    ctx = timetable_context
    client, headers = ctx["client"], ctx["headers"]
    with SessionLocal() as db:
        db.get(Teacher, ctx["lesson"]["teacher_id"]).availability_json = json.dumps(
            {"MON": ["P1", "P2"], "TUE": ["P1", "P2"], "WED": [], "THU": [], "FRI": []}
        )
        db.commit()
    changed = client.put(
        f"{BASE}/rules/{ctx['rule_id']}",
        json={
            **ctx["rule"],
            "expected_version": 1,
            "is_active": True,
            "rule": {"max_lessons_per_day": 2, "allowed_days": ["MON", "TUE", "THU"], "allowed_periods": ["P1", "P2"]},
        },
        headers=headers["admin"],
    )
    assert changed.status_code == 200
    version = _draft(ctx)
    assert _place(ctx, version, start_period="LUNCH").status_code == 422
    for changes, reason in (
        ({"start_period": "P2"}, "lunch"),
        ({"weekday": "WED"}, "weekday"),
        ({"weekday": "THU"}, "unavailable"),
        ({"weekday": "TUE", "start_period": "P3"}, "teaching period"),
        ({"period_count": 1}, "block pattern"),
    ):
        response = _place(ctx, version, **changes)
        assert response.status_code == 409, response.text
        assert reason in response.json()["detail"]
    monday = _place(ctx, version)
    assert monday.status_code == 201
    version = monday.json()
    daily = _place(ctx, version, start_period="P3")
    assert daily.status_code == 409 and "daily" in daily.json()["detail"]
    tuesday = _place(ctx, version, weekday="TUE")
    assert tuesday.status_code == 201
    assert _place(ctx, tuesday.json(), weekday="FRI").status_code == 409


def test_week_wide_rule_resolution_and_changed_configuration_block_draft_writes(timetable_context):
    ctx = timetable_context
    client, headers = ctx["client"], ctx["headers"]
    for changes in ({"week_start": "2026-10-20"}, {"class_ids": ctx["draft"]["class_ids"] * 2}):
        assert client.post(f"{BASE}/versions", json={**ctx["draft"], **changes}, headers=headers["operator"]).status_code == 422
    assert client.post(f"{BASE}/versions", json=ctx["draft"], headers=headers["executive"]).status_code == 403
    version = _draft(ctx)
    changed = client.put(
        f"{BASE}/rules/{ctx['rule_id']}",
        json={**ctx["rule"], "effective_to": "2026-10-21", "expected_version": 1, "is_active": True},
        headers=headers["admin"],
    )
    assert changed.status_code == 200
    assert (
        client.post(f"{BASE}/versions", json=ctx["draft"], headers=headers["operator"]).status_code == 409
    )  # Thursday/Friday are uncovered
    assert _place(ctx, version).status_code == 409
    continuation = client.post(
        f"{BASE}/rules", json={**ctx["rule"], "effective_from": "2026-10-22", "rule": {"max_lessons_per_day": 1}}, headers=headers["admin"]
    )
    assert continuation.status_code == 201
    assert _place(ctx, version).status_code == 409  # rules now exist, but the original snapshot is stale
    fresh = _draft(ctx)
    rule_days = fresh["snapshot"]["classes"][str(ctx["lesson"]["instructional_class_id"])]["rules"]
    assert rule_days["MON"]["rule_id"] == ctx["rule_id"]
    assert rule_days["THU"]["rule_id"] == continuation.json()["id"]
    assert _place(ctx, fresh, weekday="THU").status_code == 409
    unchanged = client.get(f"{BASE}/versions/{version['id']}", headers=headers["operator"]).json()
    assert unchanged["revision"] == 1 and unchanged["placements"] == []


def test_swap_checks_the_second_destination_and_rolls_back(timetable_context):
    ctx = timetable_context
    client, headers = ctx["client"], ctx["headers"]
    _single_requirement(ctx, count=1)
    teacher = client.post(
        f"{BASE}/teachers",
        json={
            "short_code": f"X{uuid4().hex[:10]}",
            "full_name": "Tuesday Teacher",
            "availability": {"MON": [], "TUE": ["P1"], "WED": [], "THU": [], "FRI": []},
        },
        headers=headers["admin"],
    )
    assert teacher.status_code == 201
    other = client.post(
        f"{BASE}/lessons",
        json={**ctx["lesson"], "teacher_id": teacher.json()["id"], "weekly_count": 1, "block_length": 1},
        headers=headers["operator"],
    )
    assert other.status_code == 201
    version = _draft(ctx)
    first = _place(ctx, version, period_count=1)
    assert first.status_code == 201
    second = _place(ctx, first.json(), lesson_requirement_id=other.json()["id"], weekday="TUE", period_count=1)
    assert second.status_code == 201
    version = second.json()
    first_id, second_id = [block["id"] for block in version["placements"]]
    class_clash = client.put(
        f"{BASE}/versions/{version['id']}/placements/{first_id}",
        json=_body(ctx, version, weekday="TUE", period_count=1),
        headers=headers["operator"],
    )
    assert class_clash.status_code == 409 and "class conflict" in class_clash.json()["detail"]
    swapped = client.post(
        f"{BASE}/versions/{version['id']}/swap",
        json={"expected_revision": 3, "first_placement_id": first_id, "second_placement_id": second_id},
        headers=headers["operator"],
    )
    assert swapped.status_code == 409 and "unavailable" in swapped.json()["detail"]
    assert client.get(f"{BASE}/versions/{version['id']}", headers=headers["operator"]).json() == version


def test_teacher_clashes_use_actual_overridden_times_and_database_guards(timetable_context):
    ctx = timetable_context
    client, headers = ctx["client"], ctx["headers"]
    _single_requirement(ctx)
    other_class = client.post(
        f"{BASE}/classes", json={"code": f"O{uuid4().hex[:10]}", "name": "Different period times"}, headers=headers["admin"]
    )
    assert other_class.status_code == 201
    other_id = other_class.json()["id"]
    assert client.post(f"{BASE}/rules", json={**ctx["rule"], "target_id": other_id}, headers=headers["admin"]).status_code == 201
    other_lesson = client.post(
        f"{BASE}/lessons",
        json={**ctx["lesson"], "instructional_class_id": other_id, "weekly_count": 2, "block_length": 1},
        headers=headers["operator"],
    )
    assert other_lesson.status_code == 201
    for code, start, end in (("P1", "07:00", "08:00"), ("P2", "09:00", "10:00")):
        response = client.post(
            f"{BASE}/periods",
            json={"scope": "CLASS", "target_id": other_id, "slot_code": code, "label": code, "starts_at": start, "ends_at": end},
            headers=headers["admin"],
        )
        assert response.status_code == 201
    version = _draft(ctx, class_ids=[ctx["lesson"]["instructional_class_id"], other_id])
    first = _place(ctx, version, period_count=1)
    assert first.status_code == 201
    version = first.json()
    clash = _place(ctx, version, lesson_requirement_id=other_lesson.json()["id"], start_period="P2", period_count=1)
    assert clash.status_code == 409 and "teacher conflict" in clash.json()["detail"]  # P2 overlaps another class's P1
    early = _place(ctx, version, lesson_requirement_id=other_lesson.json()["id"], period_count=1)
    assert early.status_code == 201
    if engine.dialect.name == "postgresql":
        version = early.json()
        parent = next(block for block in version["placements"] if block["lesson_requirement_id"] == other_lesson.json()["id"])
        with SessionLocal() as db:
            db.add(
                TimetableSlot(
                    placement_id=parent["id"],
                    version_id=version["id"],
                    instructional_class_id=other_id,
                    teacher_id=ctx["lesson"]["teacher_id"],
                    subject_id=ctx["lesson"]["subject_id"],
                    weekday="MON",
                    slot_code="P2",
                    starts_at=time(9),
                    ends_at=time(10),
                )
            )
            with pytest.raises(IntegrityError) as error:
                db.flush()
            assert "double-booked" in str(error.value)
            db.rollback()


def test_concurrent_draft_writes_use_revision_and_do_not_leave_partial_cells(timetable_context):
    ctx = timetable_context
    version = _draft(ctx)
    barrier = Barrier(2)

    def add(day):
        barrier.wait(timeout=10)
        return _place(ctx, version, weekday=day)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(add, ("MON", "TUE")))
    assert sorted(result.status_code for result in results) == [201, 409]
    current = ctx["client"].get(f"{BASE}/versions/{version['id']}", headers=ctx["headers"]["operator"]).json()
    assert current["revision"] == 2 and len(current["placements"]) == 1
    assert len(current["placements"][0]["slots"]) == 2


def test_remainder_block_preserves_exact_weekly_total(timetable_context):
    ctx = timetable_context
    client, headers = ctx["client"], ctx["headers"]
    response = client.put(
        f"{BASE}/lessons/{ctx['lesson_id']}",
        json={**ctx["lesson"], "weekly_count": 3, "expected_version": 1, "is_active": True},
        headers=headers["operator"],
    )
    assert response.status_code == 200
    version = _draft(ctx)
    single = _place(ctx, version, start_period="P3", period_count=1)
    assert single.status_code == 201
    version = single.json()
    assert _place(ctx, version, weekday="TUE", period_count=1).status_code == 409
    double = _place(ctx, version, weekday="TUE")
    assert double.status_code == 201
    assert double.json()["pending"] == []
    assert sum(len(block["slots"]) for block in double.json()["placements"]) == 3


def test_postgresql_snapshots_locked_blocks_and_approved_versions_are_protected(timetable_context):
    if engine.dialect.name != "postgresql":
        pytest.skip("Production database protections require PostgreSQL")
    ctx = timetable_context
    _single_requirement(ctx, count=1)
    version = _draft(ctx)
    placed = _place(ctx, version, period_count=1)
    assert placed.status_code == 201
    version = placed.json()
    block_id = version["placements"][0]["id"]
    with SessionLocal() as db:
        db.get(TimetableVersion, version["id"]).snapshot_json = "{}"
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()
    lock = ctx["client"].patch(
        f"{BASE}/versions/{version['id']}/placements/{block_id}/lock",
        json={"expected_revision": 2, "is_locked": True},
        headers=ctx["headers"]["operator"],
    )
    assert lock.status_code == 200
    with SessionLocal() as db:
        with pytest.raises(IntegrityError):
            db.execute(delete(TimetableSlot).where(TimetableSlot.placement_id == block_id))
        db.rollback()
    approved = ctx["client"].post(
        f"{BASE}/versions/{version['id']}/approve", json={"expected_revision": 3}, headers=ctx["headers"]["admin"]
    )
    assert approved.status_code == 200
    for model, record_id, field, value in (
        (TimetableVersion, version["id"], "name", "Tampered"),
        (TimetablePlacement, block_id, "is_locked", False),
    ):
        with SessionLocal() as db:
            setattr(db.get(model, record_id), field, value)
            with pytest.raises(IntegrityError):
                db.flush()
            db.rollback()
    with SessionLocal() as db:
        with pytest.raises(IntegrityError):
            db.execute(delete(TimetableSlot).where(TimetableSlot.placement_id == block_id))
        db.rollback()
        with pytest.raises(IntegrityError):
            db.execute(delete(TimetableVersionClass).where(TimetableVersionClass.version_id == version["id"]))
        db.rollback()


@pytest.mark.parametrize("damage", ["missing_cell", "extra_cell", "changed_block"])
def test_inconsistent_stored_cells_block_approval_and_all_amendments(timetable_context, damage):
    ctx = timetable_context
    _single_requirement(ctx, count=1)
    version = _place(ctx, _draft(ctx), period_count=1).json()
    block_id = version["placements"][0]["id"]
    path = f"{BASE}/versions/{version['id']}"
    with SessionLocal() as db:
        if damage == "missing_cell":
            db.execute(delete(TimetableSlot).where(TimetableSlot.placement_id == block_id))
        elif damage == "extra_cell":
            # A valid snapshotted cell can still be outside its parent's declared block.
            db.add(
                TimetableSlot(
                    placement_id=block_id,
                    version_id=version["id"],
                    instructional_class_id=ctx["lesson"]["instructional_class_id"],
                    teacher_id=ctx["lesson"]["teacher_id"],
                    subject_id=ctx["lesson"]["subject_id"],
                    weekday="MON",
                    slot_code="P2",
                    starts_at=time(10, 15),
                    ends_at=time(12),
                )
            )
        else:
            db.get(TimetablePlacement, block_id).start_period = "P3"
        db.commit()
        audit_ids = list(db.scalars(select(AuditEvent.id).where(AuditEvent.entity_id == str(version["id"]))).all())

    before = ctx["client"].get(path, headers=ctx["headers"]["operator"]).json()
    revision = {"expected_revision": version["revision"]}
    responses = [
        ctx["client"].post(path + "/approve", json=revision, headers=ctx["headers"]["admin"]),
        ctx["client"].patch(
            path + f"/placements/{block_id}/lock", json={**revision, "is_locked": True}, headers=ctx["headers"]["operator"]
        ),
        ctx["client"].delete(path + f"/placements/{block_id}?expected_revision={version['revision']}", headers=ctx["headers"]["operator"]),
        _place(ctx, version, weekday="TUE", period_count=1),
        ctx["client"].put(path + f"/placements/{block_id}", json=_body(ctx, version, period_count=1), headers=ctx["headers"]["operator"]),
    ]
    assert all(response.status_code == 409 for response in responses)
    assert all("Stored timetable cells" in response.json()["detail"] for response in responses)
    assert ctx["client"].get(path, headers=ctx["headers"]["operator"]).json() == before
    with SessionLocal() as db:
        assert list(db.scalars(select(AuditEvent.id).where(AuditEvent.entity_id == str(version["id"]))).all()) == audit_ids
