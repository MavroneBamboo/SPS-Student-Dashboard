from conftest import ensure_academic_year
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditEvent, TimetableVersion


def _approved_week(lesson_context, *, name="Publishable timetable", start_period="P1"):
    client, headers, references = lesson_context
    academic_year = f"PUB-{references['instructional_class_id']}"
    ensure_academic_year(client, headers, academic_year)
    requirement = client.post(
        "/api/v1/timetable/lessons",
        json={**references, "academic_year": academic_year, "weekly_count": 2, "block_length": 1},
        headers=headers["operator"],
    )
    assert requirement.status_code == 201, requirement.text
    rule = client.post(
        "/api/v1/timetable/rules",
        json={
            "academic_year": academic_year,
            "target_type": "CLASS",
            "target_id": references["instructional_class_id"],
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
            "rule": {},
        },
        headers=headers["admin"],
    )
    assert rule.status_code == 201, rule.text
    version = client.post(
        "/api/v1/timetable/versions",
        json={
            "name": name,
            "academic_year": academic_year,
            "week_start": "2026-10-19",
            "class_ids": [references["instructional_class_id"]],
        },
        headers=headers["operator"],
    )
    assert version.status_code == 201, version.text
    for day in ("MON", "TUE"):
        result = client.post(
            f"/api/v1/timetable/versions/{version.json()['id']}/placements",
            json={
                "expected_revision": version.json()["revision"],
                "lesson_requirement_id": requirement.json()["id"],
                "weekday": day,
                "start_period": start_period,
                "period_count": 1,
            },
            headers=headers["operator"],
        )
        assert result.status_code == 201, result.text
        version = result
    approved = client.post(
        f"/api/v1/timetable/versions/{version.json()['id']}/approve",
        json={"expected_revision": version.json()["revision"]},
        headers=headers["admin"],
    )
    assert approved.status_code == 200, approved.text
    return client, headers, approved.json()


def _replacement_week(client, headers, prior, *, name, start_period):
    class_id = int(next(iter(prior["snapshot"]["classes"])))
    requirement_id = int(next(iter(prior["snapshot"]["requirements"])))
    version = client.post(
        "/api/v1/timetable/versions",
        json={"name": name, "academic_year": prior["academic_year"], "week_start": prior["week_start"], "class_ids": [class_id]},
        headers=headers["operator"],
    )
    assert version.status_code == 201, version.text
    for day in ("MON", "TUE"):
        updated = client.post(
            f"/api/v1/timetable/versions/{version.json()['id']}/placements",
            json={
                "expected_revision": version.json()["revision"],
                "lesson_requirement_id": requirement_id,
                "weekday": day,
                "start_period": start_period,
                "period_count": 1,
            },
            headers=headers["operator"],
        )
        assert updated.status_code == 201, updated.text
        version = updated
    approved = client.post(
        f"/api/v1/timetable/versions/{version.json()['id']}/approve",
        json={"expected_revision": version.json()["revision"]},
        headers=headers["admin"],
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def test_only_it_can_publish_and_replace_the_current_week_without_changing_grid_revision(lesson_context):
    client, headers, first = _approved_week(lesson_context)
    query = f"/api/v1/timetable/published?academic_year={first['academic_year']}&week_start={first['week_start']}"
    assert client.get(query, headers=headers["executive"]).json() == []
    assert (
        client.post(
            f"/api/v1/timetable/versions/{first['id']}/publish",
            json={"expected_revision": first["revision"]},
            headers=headers["operator"],
        ).status_code
        == 403
    )

    published = client.post(
        f"/api/v1/timetable/versions/{first['id']}/publish",
        json={"expected_revision": first["revision"]},
        headers=headers["admin"],
    )
    assert published.status_code == 200, published.text
    assert published.json()["is_published"] is True
    assert published.json()["revision"] == first["revision"]
    visible = client.get(query, headers=headers["executive"])
    assert visible.status_code == 200
    assert [row["id"] for row in visible.json()] == [first["id"]]

    replacement = _replacement_week(client, headers, first, name="Replacement", start_period="P2")
    replaced = client.post(
        f"/api/v1/timetable/versions/{replacement['id']}/publish",
        json={"expected_revision": replacement["revision"]},
        headers=headers["admin"],
    )
    assert replaced.status_code == 200, replaced.text
    assert replaced.json()["is_published"] is True
    visible = client.get(query, headers=headers["operator"]).json()
    assert [row["id"] for row in visible] == [replacement["id"]]
    with SessionLocal() as db:
        previous = db.get(TimetableVersion, first["id"])
        current = db.get(TimetableVersion, replacement["id"])
        assert previous.status == "APPROVED" and previous.is_published is False
        assert previous.published_by is not None and previous.published_at is not None
        assert current.status == "APPROVED" and current.is_published is True
        actions = list(
            db.scalars(
                select(AuditEvent.action).where(
                    AuditEvent.entity_type == "timetable_version",
                    AuditEvent.action == "timetable.version.published",
                )
            ).all()
        )
        assert len(actions) >= 2

    restored = client.post(
        f"/api/v1/timetable/versions/{first['id']}/publish",
        json={"expected_revision": first["revision"]},
        headers=headers["admin"],
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["is_published"] is True
    assert [row["id"] for row in client.get(query, headers=headers["operator"]).json()] == [first["id"]]

    removed = client.post(
        f"/api/v1/timetable/versions/{first['id']}/unpublish",
        json={"expected_revision": first["revision"]},
        headers=headers["admin"],
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["is_published"] is False
    assert client.get(query, headers=headers["executive"]).json() == []


def test_draft_stale_revision_and_non_current_unpublish_are_rejected(lesson_context):
    client, headers, version = _approved_week(lesson_context)
    draft = client.post(
        "/api/v1/timetable/versions",
        json={
            "name": "Unapproved replacement",
            "academic_year": version["academic_year"],
            "week_start": version["week_start"],
            "class_ids": [int(next(iter(version["snapshot"]["classes"])))],
        },
        headers=headers["operator"],
    )
    assert draft.status_code == 201, draft.text
    assert (
        client.post(
            f"/api/v1/timetable/versions/{draft.json()['id']}/publish",
            json={"expected_revision": draft.json()["revision"]},
            headers=headers["admin"],
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/timetable/versions/{version['id']}/publish",
            json={"expected_revision": version["revision"] - 1},
            headers=headers["admin"],
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/v1/timetable/versions/{version['id']}/unpublish",
            json={"expected_revision": version["revision"]},
            headers=headers["admin"],
        ).status_code
        == 409
    )
    assert client.get(f"/api/v1/timetable/published?academic_year={version['academic_year']}", headers=headers["operator"]).json() == []
