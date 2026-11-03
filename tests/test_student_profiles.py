import json
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.crypto import decrypt_sensitive
from app.db import SessionLocal
from app.models import AuditEvent, Student, StudentStatusHistory

BASE = "/api/v1/students"


def _create(ctx, **changes):
    client, headers, _ = ctx
    payload = {
        "pris_no": f"PROFILE-{uuid4().hex[:12]}",
        "name": "Profile Fixture",
        "class_name": "Profile Class",
        "class_effective_date": "2026-10-01",
        "category": "OP",
        "status": "ACTIVE",
        "status_effective": "2026-10-01",
        "date_of_birth": "2000-01-02",
        **changes,
    }
    response = client.post(BASE, json=payload, headers=headers["operator"])
    assert response.status_code == 201, response.text
    return response.json()


def test_profile_versions_encryption_history_and_stale_save_preserve_winner(lesson_context):
    client, headers, _ = lesson_context
    profile = _create(lesson_context)
    path = f"{BASE}/{profile['id']}"
    assert profile["version"] == 1
    assert client.get(path, headers=headers["operator"]).json() == profile
    edited = client.patch(
        path,
        json={"expected_version": 1, "name": "Revised Profile", "date_of_birth": None, "status": "INACTIVE"},
        headers=headers["operator"],
    )
    assert edited.status_code == 200, edited.text
    saved = edited.json()
    assert saved["version"] == 2 and saved["date_of_birth"] is None
    assert saved["status_effective"] == date.today().isoformat()
    assert (
        client.patch(path, json={"expected_version": 1, "name": "Stale edit", "status": "ACTIVE"}, headers=headers["operator"]).status_code
        == 409
    )
    assert client.get(path, headers=headers["operator"]).json() == saved
    history = client.get(path + "/status-history", headers=headers["operator"]).json()
    assert [row["new_status"] for row in history] == ["ACTIVE", "INACTIVE"]
    assert history[-1]["effective_date"] == saved["status_effective"]
    with SessionLocal() as db:
        stored = db.get(Student, profile["id"])
        assert stored.name_encrypted != saved["name"] and stored.date_of_birth_encrypted is None
        audit = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "student", AuditEvent.entity_id == str(profile["id"]), AuditEvent.action == "student.updated"
            )
        ).one()
        details = json.loads(audit.details_json)
        assert details["version"] == 2 and "Revised Profile" not in audit.details_json


def test_profile_validation_permissions_and_stable_identifier(lesson_context):
    client, headers, _ = lesson_context
    profile = _create(lesson_context)
    path = f"{BASE}/{profile['id']}"
    for body in (
        {"name": "No version"},
        {"expected_version": 0, "name": "Invalid"},
        {"expected_version": 1},
        {"expected_version": 1, "pris_no": "REKEY"},
        {"expected_version": 1, "name": "   "},
        {"expected_version": 1, "class_name": None},
        {"expected_version": 1, "status_effective": "2026-09-01"},
        {"expected_version": 1, "class_effective_date": "2026-09-01"},
    ):
        assert client.patch(path, json=body, headers=headers["operator"]).status_code == 422
    assert client.patch(path, json={"expected_version": 1, "age_in_academic_year": 121}, headers=headers["operator"]).status_code == 422
    assert client.patch(path, json={"expected_version": 1, "age_in_academic_year": 20}, headers=headers["operator"]).status_code == 422
    assert (
        client.post(
            BASE,
            json={"pris_no": "AGE-YEAR-MISSING", "name": "Synthetic", "class_name": "Class", "category": "OP", "age_in_academic_year": 20},
            headers=headers["operator"],
        ).status_code
        == 422
    )
    assert client.get(path, headers=headers["executive"]).status_code == 403
    assert client.patch(path, json={"expected_version": 1, "name": "Denied"}, headers=headers["executive"]).status_code == 403
    assert client.get(f"{BASE}/999999999", headers=headers["operator"]).status_code == 404
    assert client.get(path, headers=headers["operator"]).json() == profile
    duplicate = {key: value for key, value in profile.items() if key not in {"id", "version", "category_id", "institution_name"}}
    duplicate["pris_no"] = " " + profile["pris_no"].lower() + " "
    assert client.post(BASE, json=duplicate, headers=headers["operator"]).status_code == 409
    assert client.get(BASE + "?limit=101", headers=headers["operator"]).status_code == 422


def test_class_history_is_audited_and_rejects_future_effective_dates(lesson_context):
    client, headers, _ = lesson_context
    profile = _create(lesson_context)
    path = f"{BASE}/{profile['id']}"
    history = client.get(path + "/class-history", headers=headers["operator"])
    assert history.status_code == 200
    assert len(history.json()) == 1
    assert history.json()[0]["class_name"] == profile["class_name"]
    assert history.json()[0]["effective_date"] == "2026-10-01"
    assert history.json()[0]["source"] == "PROFILE"
    assert history.json()[0]["changed_by"] > 0
    future = client.patch(
        path,
        json={"expected_version": profile["version"], "class_name": "Future Class", "class_effective_date": "2099-01-01"},
        headers=headers["operator"],
    )
    assert future.status_code == 422
    assert client.get(path, headers=headers["operator"]).json()["class_name"] == profile["class_name"]


def test_extended_intake_profile_round_trip_encrypts_sensitive_fields_and_allows_clearing(lesson_context):
    client, headers, _ = lesson_context
    encrypted_fields = {
        "ic_number": ("ic_number_encrypted", "SYNTH-IC-001"),
        "gender": ("gender_encrypted", "Synthetic gender"),
        "nationality": ("nationality_encrypted", "Synthetic nationality"),
        "citizenship": ("citizenship_encrypted", "Synthetic citizenship"),
        "birthplace": ("birthplace_encrypted", "Synthetic birthplace"),
        "religion": ("religion_encrypted", "Synthetic religion"),
        "race": ("race_encrypted", "Synthetic race"),
        "marital_status": ("marital_status_encrypted", "Synthetic marital status"),
        "next_of_kin_name": ("next_of_kin_name_encrypted", "Synthetic next of kin"),
        "next_of_kin_nric": ("next_of_kin_nric_encrypted", "SYNTH-NRIC-001"),
        "next_of_kin_relationship": ("next_of_kin_relationship_encrypted", "Synthetic relationship"),
        "next_of_kin_contact": ("next_of_kin_contact_encrypted", "0000-0000"),
        "next_of_kin_address_ports": ("next_of_kin_address_ports_encrypted", "Synthetic port address"),
        "next_of_kin_address_from_student": ("next_of_kin_address_from_student_encrypted", "Synthetic student address"),
        "student_contact": ("student_contact_encrypted", "1111-1111"),
    }
    plain_fields = {
        "edr_ros": "Synthetic EDR/ROS",
        "admission_type": "Synthetic admission",
        "exam_level": "Synthetic exam level",
        "academic_year": "2023",
        "age_in_academic_year": 23,
        "language_1": "Synthetic language 1",
        "language_2": "Synthetic language 2",
        "math_1": "Synthetic math 1",
        "math_2": "Synthetic math 2",
        "cpa": "Synthetic CPA",
        "science": "Synthetic science",
        "humanities": "Synthetic humanities",
        "commerce_1": "Synthetic commerce 1",
        "commerce_2": "Synthetic commerce 2",
        "commerce_3": "Synthetic commerce 3",
        "aa": "Synthetic AA",
    }
    profile = _create(lesson_context, **{field: value for field, (_, value) in encrypted_fields.items()}, **plain_fields)
    for field, (_, value) in encrypted_fields.items():
        assert profile[field] == value
    for field, value in plain_fields.items():
        assert profile[field] == value

    with SessionLocal() as db:
        stored = db.get(Student, profile["id"])
        for _, (column, value) in encrypted_fields.items():
            ciphertext = getattr(stored, column)
            assert ciphertext != value and decrypt_sensitive(ciphertext) == value
    edited = client.patch(
        f"{BASE}/{profile['id']}",
        json={"expected_version": 1, "ic_number": None, "next_of_kin_contact": "2222-2222", "commerce_1": None},
        headers=headers["operator"],
    )
    assert edited.status_code == 200, edited.text
    saved = edited.json()
    assert saved["version"] == 2 and saved["ic_number"] is None
    assert saved["next_of_kin_contact"] == "2222-2222" and saved["commerce_1"] is None
    with SessionLocal() as db:
        stored = db.get(Student, profile["id"])
        assert stored.ic_number_encrypted is None
        assert stored.next_of_kin_contact_encrypted != "2222-2222"
        audit = db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "student", AuditEvent.entity_id == str(profile["id"]), AuditEvent.action == "student.updated"
            )
        ).one()
        assert "2222-2222" not in audit.details_json and "SYNTH-NRIC-001" not in audit.details_json


def test_profile_search_and_pagination_filter_before_slicing(lesson_context):
    client, headers, _ = lesson_context
    marker = "SEARCH-" + uuid4().hex[:8]
    rows = [
        _create(lesson_context, pris_no=f"{marker}-{index}", name=f"Find {marker}", status="ACTIVE" if index != 1 else "INACTIVE")
        for index in range(3)
    ]
    query = f"{BASE}?q={marker}&status=ACTIVE&class_name=Profile%20Class&limit=1"
    first = client.get(query, headers=headers["operator"]).json()
    second = client.get(query + "&offset=1", headers=headers["operator"]).json()
    assert [first[0]["id"], second[0]["id"]] == [rows[0]["id"], rows[2]["id"]]
    assert client.get(query + "&offset=2", headers=headers["operator"]).json() == []
    assert len(client.get(BASE + f"?q=Find%20{marker}", headers=headers["operator"]).json()) == 3


def test_concurrent_profile_edits_commit_one_version_history_and_audit(lesson_context):
    client, headers, _ = lesson_context
    profile = _create(lesson_context)
    path = f"{BASE}/{profile['id']}"
    barrier = Barrier(2)

    def edit(name):
        barrier.wait(timeout=10)
        return client.patch(
            path,
            json={"expected_version": 1, "name": name, "status": "INACTIVE", "status_effective": "2026-10-02"},
            headers=headers["operator"],
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(edit, ("First edit", "Second edit")))
    assert sorted(response.status_code for response in responses) == [200, 409]
    winner = next(response.json() for response in responses if response.status_code == 200)
    assert client.get(path, headers=headers["operator"]).json() == winner
    with SessionLocal() as db:
        assert len(db.scalars(select(StudentStatusHistory).where(StudentStatusHistory.student_id == profile["id"])).all()) == 2
        assert (
            len(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.entity_type == "student",
                        AuditEvent.entity_id == str(profile["id"]),
                        AuditEvent.action == "student.updated",
                    )
                ).all()
            )
            == 1
        )


def test_profile_transaction_failure_rolls_back_record_history_and_audit(lesson_context, monkeypatch):
    from app.routes import students

    client, headers, _ = lesson_context
    profile = _create(lesson_context)
    original = students.record_event

    def fail(db, *args, **kwargs):
        original(db, *args, **kwargs)
        raise RuntimeError("Injected audit failure")

    monkeypatch.setattr(students, "record_event", fail)
    path = f"{BASE}/{profile['id']}"
    with pytest.raises(RuntimeError, match="Injected audit failure"):
        client.patch(path, json={"expected_version": 1, "name": "Must roll back", "status": "INACTIVE"}, headers=headers["operator"])
    assert client.get(path, headers=headers["operator"]).json() == profile
    with SessionLocal() as db:
        assert len(db.scalars(select(StudentStatusHistory).where(StudentStatusHistory.student_id == profile["id"])).all()) == 1
        assert not db.scalars(
            select(AuditEvent).where(
                AuditEvent.entity_type == "student", AuditEvent.entity_id == str(profile["id"]), AuditEvent.action == "student.updated"
            )
        ).all()
