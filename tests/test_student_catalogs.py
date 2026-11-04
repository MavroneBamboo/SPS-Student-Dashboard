import json
from uuid import uuid4

from sqlalchemy import select

from app.db import SessionLocal
from app.models import AuditEvent


def test_catalog_permissions_normalization_archive_and_versioning(lesson_context):
    client, headers, _ = lesson_context
    path = "/api/v1/student-reference/catalogs/categories"
    assert client.get(path, headers=headers["operator"]).status_code == 200
    assert client.get(path, headers=headers["executive"]).status_code == 200
    assert client.post(path, json={"name": "Denied"}, headers=headers["operator"]).status_code == 403

    name = f"Release {uuid4().hex[:8]}"
    created = client.post(path, json={"name": f"  {name}  ", "description": "Synthetic category"}, headers=headers["admin"])
    assert created.status_code == 201, created.text
    saved = created.json()
    assert saved["name"] == name and saved["catalog_type"] == "CATEGORY" and saved["version"] == 1
    duplicate = client.post(path, json={"name": f" {name.swapcase()} "}, headers=headers["superuser"])
    assert duplicate.status_code == 409

    value_path = f"{path}/{saved['id']}"
    revised = client.patch(value_path, json={"expected_version": 1, "name": f"{name} Revised"}, headers=headers["admin"])
    assert revised.status_code == 200 and revised.json()["version"] == 2
    stale = client.patch(value_path, json={"expected_version": 1, "name": "Stale"}, headers=headers["admin"])
    assert stale.status_code == 409
    assert (
        client.patch(value_path, json={"expected_version": 2, "effective_from": "2026-01-01"}, headers=headers["admin"]).status_code == 422
    )
    assert client.patch(value_path, json={"expected_version": 2, "is_active": None}, headers=headers["admin"]).status_code == 422

    archived = client.patch(value_path, json={"expected_version": 2, "is_active": False}, headers=headers["admin"])
    assert archived.status_code == 200 and archived.json()["is_active"] is False and archived.json()["version"] == 3
    active = client.get(path, headers=headers["operator"]).json()
    assert saved["id"] not in {item["id"] for item in active}
    history = client.get(path + "?include_inactive=true", headers=headers["operator"]).json()
    assert next(item for item in history if item["id"] == saved["id"])["is_active"] is False
    restored = client.patch(value_path, json={"expected_version": 3, "is_active": True}, headers=headers["superuser"])
    assert restored.status_code == 200 and restored.json()["version"] == 4

    with SessionLocal() as db:
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "student_reference_value", AuditEvent.entity_id == str(saved["id"]))
        ).all()
        actions = [event.action for event in events]
        assert actions.count("student_reference.created") == 1
        assert actions.count("student_reference.updated") == 3
        assert all(json.loads(event.details_json)["catalog_type"] == "CATEGORY" for event in events)


def test_academic_year_catalog_dates_and_invalid_catalogs(lesson_context):
    client, headers, _ = lesson_context
    path = "/api/v1/student-reference/catalogs/academic-years"
    invalid = client.post(
        path,
        json={"name": f"AY-{uuid4().hex[:8]}", "effective_from": "2026-12-31", "effective_to": "2026-01-01"},
        headers=headers["admin"],
    )
    assert invalid.status_code == 422
    created = client.post(
        path,
        json={"name": f"AY-{uuid4().hex[:8]}", "effective_from": "2026-01-01", "effective_to": "2026-12-31"},
        headers=headers["admin"],
    )
    assert created.status_code == 201, created.text
    assert created.json()["effective_to"] == "2026-12-31"
    assert client.get("/api/v1/student-reference/catalogs/unknown", headers=headers["admin"]).status_code == 404

    institution_path = "/api/v1/student-reference/catalogs/institutions"
    dates_rejected = client.post(
        institution_path, json={"name": f"Institution-{uuid4().hex[:8]}", "effective_from": "2026-01-01"}, headers=headers["admin"]
    )
    assert dates_rejected.status_code == 422
