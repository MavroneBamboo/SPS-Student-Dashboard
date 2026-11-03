def _approved_week(lesson_context):
    client, headers, references = lesson_context
    academic_year = f"ATT-{references['instructional_class_id']}"
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
            "name": "Published attendance test",
            "academic_year": academic_year,
            "week_start": "2026-10-19",
            "class_ids": [references["instructional_class_id"]],
        },
        headers=headers["operator"],
    )
    assert version.status_code == 201, version.text
    for day in ("MON", "TUE"):
        version = client.post(
            f"/api/v1/timetable/versions/{version.json()['id']}/placements",
            json={
                "expected_revision": version.json()["revision"],
                "lesson_requirement_id": requirement.json()["id"],
                "weekday": day,
                "start_period": "P1",
                "period_count": 1,
            },
            headers=headers["operator"],
        )
        assert version.status_code == 201, version.text
    approved = client.post(
        f"/api/v1/timetable/versions/{version.json()['id']}/approve",
        json={"expected_revision": version.json()["revision"]},
        headers=headers["admin"],
    )
    assert approved.status_code == 200, approved.text
    return client, headers, approved.json()


def test_published_timetable_prefills_attendance_and_preserves_schedule_provenance(lesson_context):
    client, headers, references = lesson_context
    client, headers, approved = _approved_week(lesson_context)
    class_name = f"ATT-{references['instructional_class_id']}"
    student = client.post(
        "/api/v1/students",
        json={
            "pris_no": f"{class_name}-001",
            "name": "Timetable Attendance Test",
            "class_name": class_name,
            "category": "OP",
            "status": "ACTIVE",
            "date_of_birth": "2000-01-02",
        },
        headers=headers["operator"],
    )
    assert student.status_code == 201, student.text
    second_student = client.post(
        "/api/v1/students",
        json={
            "pris_no": f"{class_name}-002",
            "name": "Timetable Attendance Variant",
            "class_name": class_name.lower(),
            "category": "OP",
            "status": "ACTIVE",
            "date_of_birth": "2000-01-02",
        },
        headers=headers["operator"],
    )
    assert second_student.status_code == 201, second_student.text

    mapping = client.post(
        "/api/v1/student-reference/attendance-class-mappings",
        json={"student_class_name": class_name, "instructional_class_id": references["instructional_class_id"]},
        headers=headers["admin"],
    )
    assert mapping.status_code == 201, mapping.text
    assert mapping.json()["active_students"] == 2
    assert (
        client.post(
            "/api/v1/student-reference/attendance-class-mappings",
            json={"student_class_name": f"  {class_name.lower()}  ", "instructional_class_id": references["instructional_class_id"]},
            headers=headers["admin"],
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/api/v1/student-reference/attendance-class-mappings",
            json={"student_class_name": f"OTHER-{class_name}", "instructional_class_id": references["instructional_class_id"]},
            headers=headers["operator"],
        ).status_code
        == 403
    )
    deactivated = client.patch(
        f"/api/v1/student-reference/attendance-class-mappings/{mapping.json()['id']}",
        json={"expected_version": 1, "is_active": False},
        headers=headers["admin"],
    )
    assert deactivated.status_code == 200, deactivated.text
    assert deactivated.json()["version"] == 2
    stale_mapping = client.patch(
        f"/api/v1/student-reference/attendance-class-mappings/{mapping.json()['id']}",
        json={"expected_version": 1, "is_active": True},
        headers=headers["admin"],
    )
    assert stale_mapping.status_code == 409
    replacement_mapping = client.post(
        "/api/v1/student-reference/attendance-class-mappings",
        json={"student_class_name": class_name, "instructional_class_id": references["instructional_class_id"]},
        headers=headers["admin"],
    )
    assert replacement_mapping.status_code == 201, replacement_mapping.text

    published = client.post(
        f"/api/v1/timetable/versions/{approved['id']}/publish",
        json={"expected_revision": approved["revision"]},
        headers=headers["admin"],
    )
    assert published.status_code == 200, published.text

    scheduled = client.get(
        "/api/v1/attendance/scheduled-classes",
        params={"academic_year": approved["academic_year"], "session_date": "2026-10-19"},
        headers=headers["operator"],
    )
    assert scheduled.status_code == 200, scheduled.text
    assert len(scheduled.json()) == 1
    scheduled_class = scheduled.json()[0]
    assert scheduled_class["timetable_version_id"] == approved["id"]
    assert scheduled_class["instructional_class_id"] == references["instructional_class_id"]
    assert scheduled_class["instructional_class_name"] == "Lesson Test Class"
    assert scheduled_class["class_name"] == class_name
    assert scheduled_class["active_students"] == 2
    assert scheduled_class["lesson_count"] == 1
    assert (
        client.get(
            "/api/v1/attendance/scheduled-classes",
            params={"academic_year": approved["academic_year"], "session_date": "2026-10-24"},
            headers=headers["operator"],
        ).json()
        == []
    )

    unscheduled = client.post(
        "/api/v1/attendance/sessions",
        json={
            "session_date": "2026-10-21",
            "session_type": "MORNING",
            "class_name": class_name,
            "expected_count": 2,
            "timetable_version_id": approved["id"],
            "instructional_class_id": references["instructional_class_id"],
        },
        headers=headers["operator"],
    )
    assert unscheduled.status_code == 422
    assert "no lessons" in unscheduled.json()["detail"]

    session = client.post(
        "/api/v1/attendance/sessions",
        json={
            "session_date": "2026-10-19",
            "session_type": "MORNING",
            "class_name": class_name,
            "expected_count": 2,
            "timetable_version_id": approved["id"],
            "instructional_class_id": references["instructional_class_id"],
        },
        headers=headers["operator"],
    )
    assert session.status_code == 201, session.text
    assert session.json()["timetable_version_id"] == approved["id"]
    assert session.json()["instructional_class_id"] == references["instructional_class_id"]
    detail = client.get(f"/api/v1/attendance/sessions/{session.json()['id']}", headers=headers["operator"])
    assert detail.status_code == 200
    assert detail.json()["roster_count"] == 2
    assert {entry["pris_no"] for entry in detail.json()["roster"]} == {student.json()["pris_no"], second_student.json()["pris_no"]}

    manual = client.post(
        "/api/v1/attendance/sessions",
        json={"session_date": "2026-10-21", "session_type": "MORNING", "class_name": class_name, "expected_count": 2},
        headers=headers["operator"],
    )
    assert manual.status_code == 201, manual.text
    assert manual.json()["timetable_version_id"] is None
    assert manual.json()["instructional_class_id"] is None

    unpublished = client.post(
        f"/api/v1/timetable/versions/{approved['id']}/unpublish",
        json={"expected_revision": approved["revision"]},
        headers=headers["admin"],
    )
    assert unpublished.status_code == 200, unpublished.text
    assert (
        client.get(
            "/api/v1/attendance/scheduled-classes",
            params={"academic_year": approved["academic_year"], "session_date": "2026-10-20"},
            headers=headers["operator"],
        ).json()
        == []
    )
    stale = client.post(
        "/api/v1/attendance/sessions",
        json={
            "session_date": "2026-10-20",
            "session_type": "MORNING",
            "class_name": class_name,
            "expected_count": 1,
            "timetable_version_id": approved["id"],
            "instructional_class_id": references["instructional_class_id"],
        },
        headers=headers["operator"],
    )
    assert stale.status_code == 409
