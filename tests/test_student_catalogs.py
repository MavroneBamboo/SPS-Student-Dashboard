from uuid import uuid4

from app.db import SessionLocal
from app.models import AuditEvent, Student, StudentCategory

BASE = "/api/v1/student-reference"
STUDENTS = "/api/v1/students"


def test_reference_catalogs_are_role_gated_versioned_and_audited(lesson_context):
    client, headers, _ = lesson_context
    assert {row["code"] for row in client.get(f"{BASE}/categories", headers=headers["operator"]).json()} >= {"OP", "RT"}
    assert (
        client.post(f"{BASE}/categories", json={"code": "restricted", "name": "Restricted"}, headers=headers["operator"]).status_code == 403
    )
    assert client.get(f"{BASE}/institutions", headers=headers["executive"]).status_code == 200
    assert client.post(f"{BASE}/institutions", json={"code": "NO", "name": "No"}, headers=headers["executive"]).status_code == 403

    code = f"CAT-{uuid4().hex[:8]}"
    created = client.post(f"{BASE}/categories", json={"code": code, "name": "Example category"}, headers=headers["admin"])
    assert created.status_code == 201, created.text
    category = created.json()
    duplicate = client.post(f"{BASE}/categories", json={"code": f"  {code.lower()}  ", "name": "Duplicate"}, headers=headers["admin"])
    assert duplicate.status_code == 409
    renamed = client.patch(
        f"{BASE}/categories/{category['id']}",
        json={"expected_version": 1, "name": "Renamed category"},
        headers=headers["admin"],
    )
    assert renamed.status_code == 200 and renamed.json()["version"] == 2
    stale = client.patch(
        f"{BASE}/categories/{category['id']}",
        json={"expected_version": 1, "is_active": False},
        headers=headers["admin"],
    )
    assert stale.status_code == 409
    assert (
        client.patch(
            f"{BASE}/categories/{category['id']}", json={"expected_version": 2, "name": None}, headers=headers["admin"]
        ).status_code
        == 422
    )
    deactivated = client.patch(
        f"{BASE}/categories/{category['id']}",
        json={"expected_version": 2, "is_active": False},
        headers=headers["admin"],
    )
    assert deactivated.status_code == 200 and deactivated.json()["is_active"] is False
    with SessionLocal() as db:
        saved = db.get(StudentCategory, category["id"])
        assert saved.name == "Renamed category" and saved.version == 3 and not saved.is_active
        events = db.query(AuditEvent).filter_by(entity_type="student_category", entity_id=str(category["id"])).order_by(AuditEvent.id).all()
        assert [event.action for event in events] == ["student.category.created", "student.category.updated", "student.category.updated"]


def test_profiles_require_active_categories_and_can_use_optional_institutions(lesson_context):
    client, headers, _ = lesson_context
    category = client.post(
        f"{BASE}/categories", json={"code": f"CAT-{uuid4().hex[:8]}", "name": "Profile category"}, headers=headers["admin"]
    ).json()
    institution = client.post(
        f"{BASE}/institutions", json={"code": f"INST-{uuid4().hex[:8]}", "name": "Example institution"}, headers=headers["admin"]
    )
    assert institution.status_code == 201, institution.text
    institution = institution.json()
    payload = {
        "pris_no": f"CATALOG-{uuid4().hex[:10]}",
        "name": "Catalog Profile",
        "class_name": "Catalog Class",
        "category": category["code"].lower(),
        "institution_id": institution["id"],
        "status": "ACTIVE",
    }
    created = client.post(STUDENTS, json=payload, headers=headers["operator"])
    assert created.status_code == 201, created.text
    assert created.json()["category"] == category["code"]
    assert created.json()["category_id"] == category["id"]
    assert created.json()["institution_id"] == institution["id"]
    assert created.json()["institution_name"] == "Example institution"
    with SessionLocal() as db:
        saved = db.get(Student, created.json()["id"])
        assert saved.category_id == category["id"] and saved.institution_id == institution["id"]

    deactivated = client.patch(
        f"{BASE}/institutions/{institution['id']}",
        json={"expected_version": 1, "is_active": False},
        headers=headers["admin"],
    )
    assert deactivated.status_code == 200
    rejected = client.patch(
        f"{STUDENTS}/{created.json()['id']}",
        json={"expected_version": 1, "institution_id": institution["id"]},
        headers=headers["operator"],
    )
    assert rejected.status_code == 422
    cleared = client.patch(
        f"{STUDENTS}/{created.json()['id']}",
        json={"expected_version": 1, "institution_id": None},
        headers=headers["operator"],
    )
    assert cleared.status_code == 200 and cleared.json()["institution_id"] is None
    missing_category = client.post(
        STUDENTS, json={**payload, "pris_no": f"CATALOG-{uuid4().hex[:10]}", "category": "unknown"}, headers=headers["operator"]
    )
    assert missing_category.status_code == 422
