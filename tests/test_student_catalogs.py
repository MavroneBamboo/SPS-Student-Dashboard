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


def test_academic_year_configuration_is_privileged_versioned_audited_and_used_by_profiles(lesson_context):
    client, headers, _ = lesson_context
    assert client.get(f"{BASE}/academic-years", headers=headers["operator"]).status_code == 200
    assert client.get(f"{BASE}/academic-years", headers=headers["executive"]).status_code == 200
    payload = {
        "code": f"AY-{uuid4().hex[:8]}",
        "label": "Configured test year",
        "starts_on": "2026-01-01",
        "ends_on": "2026-12-31",
        "is_active": True,
    }
    assert client.post(f"{BASE}/academic-years", json=payload, headers=headers["operator"]).status_code == 403
    assert client.post(f"{BASE}/academic-years", json=payload, headers=headers["executive"]).status_code == 403
    created = client.post(f"{BASE}/academic-years", json={**payload, "code": f" {payload['code'].lower()} "}, headers=headers["admin"])
    assert created.status_code == 201, created.text
    year = created.json()
    assert year["code"] == payload["code"].upper() and year["version"] == 1 and year["is_active"]
    assert client.post(f"{BASE}/academic-years", json=payload, headers=headers["admin"]).status_code == 409
    invalid_dates = {**payload, "code": f"BAD-{uuid4().hex[:8]}", "starts_on": "2026-12-31", "ends_on": "2026-01-01"}
    assert client.post(f"{BASE}/academic-years", json=invalid_dates, headers=headers["admin"]).status_code == 422

    student = client.post(
        STUDENTS,
        json={
            "pris_no": f"YEAR-{uuid4().hex[:10]}",
            "name": "Academic year profile",
            "class_name": "Year test class",
            "category": "OP",
            "status": "ACTIVE",
            "academic_year": year["code"].lower(),
            "age_in_academic_year": 22,
        },
        headers=headers["operator"],
    )
    assert student.status_code == 201, student.text
    assert student.json()["academic_year"] == year["code"]
    bad_student = client.post(
        STUDENTS,
        json={
            "pris_no": f"YEAR-{uuid4().hex[:10]}",
            "name": "Unconfigured year profile",
            "class_name": "Year test class",
            "category": "OP",
            "status": "ACTIVE",
            "academic_year": "UNCONFIGURED-999",
        },
        headers=headers["operator"],
    )
    assert bad_student.status_code == 422

    changed = client.patch(
        f"{BASE}/academic-years/{year['id']}",
        json={"expected_version": 1, "label": "Revised test year"},
        headers=headers["admin"],
    )
    assert changed.status_code == 200 and changed.json()["version"] == 2
    stale = client.patch(
        f"{BASE}/academic-years/{year['id']}",
        json={"expected_version": 1, "is_active": False},
        headers=headers["admin"],
    )
    assert stale.status_code == 409
    deactivated = client.patch(
        f"{BASE}/academic-years/{year['id']}",
        json={"expected_version": 2, "is_active": False},
        headers=headers["admin"],
    )
    assert deactivated.status_code == 200 and not deactivated.json()["is_active"]
    assert (
        client.patch(
            f"{STUDENTS}/{student.json()['id']}",
            json={"expected_version": 1, "academic_year": year["code"]},
            headers=headers["operator"],
        ).status_code
        == 422
    )
    with SessionLocal() as db:
        events = db.query(AuditEvent).filter_by(entity_type="academic_year", entity_id=str(year["id"])).order_by(AuditEvent.id).all()
        assert [event.action for event in events] == [
            "student.academic_year.created",
            "student.academic_year.updated",
            "student.academic_year.updated",
        ]


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
