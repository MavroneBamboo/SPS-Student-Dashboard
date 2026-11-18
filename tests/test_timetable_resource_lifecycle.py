from uuid import uuid4

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditEvent


def test_teacher_subject_and_class_edits_use_revisions_and_preserve_references(lesson_context):
    client, headers, resources = lesson_context
    suffix = uuid4().hex[:8].upper()
    teacher_id = resources["teacher_id"]
    subject_id = resources["subject_id"]
    class_id = resources["instructional_class_id"]

    teacher = next(row for row in client.get("/api/v1/timetable/teachers", headers=headers["admin"]).json() if row["id"] == teacher_id)
    subject = next(row for row in client.get("/api/v1/timetable/subjects", headers=headers["admin"]).json() if row["id"] == subject_id)
    instructional_class = next(
        row for row in client.get("/api/v1/timetable/classes", headers=headers["admin"]).json() if row["id"] == class_id
    )
    assert len(teacher["revision"]) == len(subject["revision"]) == len(instructional_class["revision"]) == 64

    requirement = client.post(
        "/api/v1/timetable/lessons",
        json={
            "academic_year": "2026",
            "instructional_class_id": class_id,
            "teacher_id": teacher_id,
            "subject_id": subject_id,
            "weekly_count": 4,
            "block_length": 2,
        },
        headers=headers["admin"],
    )
    assert requirement.status_code == 201, requirement.text

    availability = {day: [] for day in ("MON", "TUE", "WED", "THU", "FRI")}
    unavailable = client.patch(
        f"/api/v1/timetable/teachers/{teacher_id}",
        json={"expected_revision": teacher["revision"], "availability": availability},
        headers=headers["admin"],
    )
    assert unavailable.status_code == 409

    updated_teacher = client.patch(
        f"/api/v1/timetable/teachers/{teacher_id}",
        json={"expected_revision": teacher["revision"], "short_code": f"UPDATED-{suffix}", "full_name": "Updated Teacher"},
        headers=headers["admin"],
    )
    assert updated_teacher.status_code == 200, updated_teacher.text
    assert updated_teacher.json()["short_code"] == f"UPDATED-{suffix}"
    assert updated_teacher.json()["revision"] != teacher["revision"]
    stale = client.patch(
        f"/api/v1/timetable/teachers/{teacher_id}",
        json={"expected_revision": teacher["revision"], "short_code": f"STALE-{suffix}"},
        headers=headers["admin"],
    )
    assert stale.status_code == 409
    denied = client.patch(
        f"/api/v1/timetable/teachers/{teacher_id}",
        json={"expected_revision": updated_teacher.json()["revision"], "full_name": "Operator edit"},
        headers=headers["operator"],
    )
    assert denied.status_code == 403

    updated_subject = client.patch(
        f"/api/v1/timetable/subjects/{subject_id}",
        json={"expected_revision": subject["revision"], "code": f"UPDATED-{suffix}", "name": "Updated Subject"},
        headers=headers["admin"],
    )
    assert updated_subject.status_code == 200, updated_subject.text
    assert updated_subject.json()["code"] == f"UPDATED-{suffix}"
    subject_deactivation = client.patch(
        f"/api/v1/timetable/subjects/{subject_id}",
        json={"expected_revision": updated_subject.json()["revision"], "is_active": False},
        headers=headers["admin"],
    )
    assert subject_deactivation.status_code == 409

    updated_class = client.patch(
        f"/api/v1/timetable/classes/{class_id}",
        json={"expected_revision": instructional_class["revision"], "code": f"UPDATED-{suffix}", "name": "Updated Class"},
        headers=headers["admin"],
    )
    assert updated_class.status_code == 200, updated_class.text
    assert updated_class.json()["code"] == f"UPDATED-{suffix}"
    class_deactivation = client.patch(
        f"/api/v1/timetable/classes/{class_id}",
        json={"expected_revision": updated_class.json()["revision"], "is_active": False},
        headers=headers["admin"],
    )
    assert class_deactivation.status_code == 409

    teacher_deactivation = client.patch(
        f"/api/v1/timetable/teachers/{teacher_id}",
        json={"expected_revision": updated_teacher.json()["revision"], "is_active": False},
        headers=headers["admin"],
    )
    assert teacher_deactivation.status_code == 409

    archived = client.delete(f"/api/v1/timetable/lessons/{requirement.json()['id']}?expected_version=1", headers=headers["admin"])
    assert archived.status_code == 200, archived.text
    for path, row, resource_id in (
        ("/api/v1/timetable/teachers", updated_teacher.json(), teacher_id),
        ("/api/v1/timetable/subjects", updated_subject.json(), subject_id),
        ("/api/v1/timetable/classes", updated_class.json(), class_id),
    ):
        response = client.patch(
            f"{path}/{resource_id}",
            json={"expected_revision": row["revision"], "is_active": False},
            headers=headers["admin"],
        )
        assert response.status_code == 200, response.text
        assert response.json()["is_active"] is False

    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.action.in_(("timetable.teacher.updated", "timetable.subject.updated", "timetable.class.updated"))
            )
        ).all()
        assert any(event.action == "timetable.teacher.updated" and '"short_code"' in event.details_json for event in events)


def test_individual_teacher_availability_updates_recalculate_composite_groups(lesson_context):
    client, headers, resources = lesson_context
    first_id = resources["teacher_id"]
    first = next(row for row in client.get("/api/v1/timetable/teachers", headers=headers["admin"]).json() if row["id"] == first_id)
    suffix = uuid4().hex[:8].upper()
    second = client.post(
        "/api/v1/timetable/teachers",
        json={"short_code": f"SECOND-{suffix}", "full_name": "Second Member"},
        headers=headers["admin"],
    )
    assert second.status_code == 201, second.text
    group = client.post(
        "/api/v1/timetable/teacher-groups",
        json={"short_code": f"TEAM-{suffix}", "full_name": "Revision Team", "member_ids": [first_id, second.json()["id"]]},
        headers=headers["admin"],
    )
    assert group.status_code == 201, group.text
    assert "P1" in group.json()["availability"]["MON"]

    changed_availability = {day: list(periods) for day, periods in first["availability"].items()}
    changed_availability["MON"].remove("P1")
    updated = client.patch(
        f"/api/v1/timetable/teachers/{first_id}",
        json={"expected_revision": first["revision"], "availability": changed_availability},
        headers=headers["admin"],
    )
    assert updated.status_code == 200, updated.text
    refreshed_group = next(
        row for row in client.get("/api/v1/timetable/teachers", headers=headers["admin"]).json() if row["id"] == group.json()["id"]
    )
    assert "P1" not in refreshed_group["availability"]["MON"]
    assert refreshed_group["revision"] != group.json()["revision"]
