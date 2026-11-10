from io import BytesIO

from openpyxl import load_workbook

from app.timetable_planning import snapshots_match_current

BASE = "/api/v1/timetable/fixed-events"


def _event(year, label, audience, target_ids, weekday="MON", slot="P1", *, mode="SELECTED", active=True):
    return {
        "academic_year": year,
        "label": label,
        "audience_type": audience,
        "target_mode": mode,
        "target_ids": target_ids,
        "slots": [{"weekday": weekday, "slot_code": slot}],
        "is_active": active,
    }


def test_fixed_event_role_boundaries_and_schema_validation(lesson_context):
    client, headers, refs = lesson_context
    payload = _event("2026", "Assembly", "CLASS", [refs["instructional_class_id"]])
    assert client.get(BASE, headers=headers["executive"]).status_code == 200
    assert client.post(BASE, json=payload, headers=headers["operator"]).status_code == 403
    assert client.post(BASE, json=payload, headers=headers["executive"]).status_code == 403
    for invalid in (
        {**payload, "target_mode": "ALL"},
        {**payload, "target_ids": [refs["instructional_class_id"]] * 2},
        {**payload, "slots": [payload["slots"][0], payload["slots"][0]]},
        {**payload, "slots": [{"weekday": "MON", "slot_code": "LUNCH"}]},
        {**payload, "slots": []},
        {**payload, "target_ids": [2147483647]},
    ):
        assert client.post(BASE, json=invalid, headers=headers["admin"]).status_code == 422


def test_fixed_event_overlap_detection_scope_and_optimistic_update(lesson_context):
    client, headers, refs = lesson_context
    first = client.post(
        BASE,
        json=_event("2026", "Teacher EA", "TEACHER", [refs["teacher_id"]], weekday="MON", slot="P2"),
        headers=headers["admin"],
    )
    assert first.status_code == 201, first.text
    assert first.json()["label"] == "Teacher EA"
    same_target = client.post(
        BASE,
        json=_event("2026", "Assembly duty", "TEACHER", [refs["teacher_id"]], weekday="MON", slot="P2"),
        headers=headers["admin"],
    )
    assert same_target.status_code == 409
    second_teacher = client.post(
        "/api/v1/timetable/teachers",
        json={"short_code": f"ALT{refs['teacher_id']}", "full_name": "Alternate Teacher"},
        headers=headers["admin"],
    )
    assert second_teacher.status_code == 201, second_teacher.text
    different_target = client.post(
        BASE,
        json=_event("2026", "Second teacher duty", "TEACHER", [second_teacher.json()["id"]], weekday="MON", slot="P2"),
        headers=headers["admin"],
    )
    assert different_target.status_code == 201, different_target.text
    all_targets = client.post(
        BASE,
        json=_event("2026", "All teacher assembly", "TEACHER", [], weekday="MON", slot="P2", mode="ALL"),
        headers=headers["admin"],
    )
    assert all_targets.status_code == 409
    other_year = client.post(
        BASE,
        json=_event("2027", "Assembly duty", "TEACHER", [refs["teacher_id"]], weekday="MON", slot="P2"),
        headers=headers["admin"],
    )
    assert other_year.status_code == 201, other_year.text
    class_audience = client.post(
        BASE,
        json=_event("2026", "Class assembly", "CLASS", [refs["instructional_class_id"]], weekday="MON", slot="P2"),
        headers=headers["admin"],
    )
    assert class_audience.status_code == 201, class_audience.text
    changed_payload = {
        **{key: value for key, value in first.json().items() if key not in {"id", "version"}},
        "expected_version": 1,
        "slots": [{"weekday": "TUE", "slot_code": "P2"}],
    }
    updated = client.put(f"{BASE}/{first.json()['id']}", json=changed_payload, headers=headers["admin"])
    assert updated.status_code == 200, updated.text
    assert updated.json()["version"] == 2
    assert client.put(f"{BASE}/{first.json()['id']}", json=changed_payload, headers=headers["admin"]).status_code == 409


def test_fixed_events_are_snapshotted_and_exported_for_classes_and_teachers(lesson_context):
    client, headers, refs = lesson_context
    year = f"FIXED-{refs['instructional_class_id']}"
    rule = client.post(
        "/api/v1/timetable/rules",
        json={
            "academic_year": year,
            "target_type": "CLASS",
            "target_id": refs["instructional_class_id"],
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
            "rule": {},
        },
        headers=headers["admin"],
    )
    assert rule.status_code == 201, rule.text
    for payload in (
        _event(year, "Class assembly", "CLASS", [refs["instructional_class_id"]], weekday="TUE", slot="P4"),
        _event(year, "Teacher duty", "TEACHER", [refs["teacher_id"]], weekday="WED", slot="P3"),
    ):
        response = client.post(BASE, json=payload, headers=headers["admin"])
        assert response.status_code == 201, response.text
    draft = client.post(
        "/api/v1/timetable/versions",
        json={
            "name": "Recurring event export",
            "academic_year": year,
            "week_start": "2026-10-19",
            "class_ids": [refs["instructional_class_id"]],
        },
        headers=headers["operator"],
    )
    assert draft.status_code == 201, draft.text
    snapshot = draft.json()["snapshot"]
    assert snapshot["schema_version"] == 2
    assert {event["label"] for event in snapshot["fixed_events"]} == {"Class assembly", "Teacher duty"}
    assert snapshot["teachers"][str(refs["teacher_id"])]
    report = client.get(f"/api/v1/timetable/versions/{draft.json()['id']}/reports.xlsx?kind=both", headers=headers["operator"])
    assert report.status_code == 200, report.text
    workbook = load_workbook(BytesIO(report.content), data_only=True)
    class_rows = list(workbook["By InstClass"].values)
    teacher_rows = list(workbook["By Teacher"].values)
    assert any(row[-1] == "Class assembly" for row in class_rows[1:])
    assert any(row[-1] == "Teacher duty" and row[6] == "Teacher duty" for row in teacher_rows[1:])


def test_fixed_event_change_stales_existing_draft(lesson_context):
    client, headers, refs = lesson_context
    year = f"STALE-{refs['instructional_class_id']}"
    requirement = client.post(
        "/api/v1/timetable/lessons",
        json={**refs, "academic_year": year, "weekly_count": 1, "block_length": 1},
        headers=headers["operator"],
    )
    assert requirement.status_code == 201, requirement.text
    rule = client.post(
        "/api/v1/timetable/rules",
        json={
            "academic_year": year,
            "target_type": "CLASS",
            "target_id": refs["instructional_class_id"],
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
            "rule": {},
        },
        headers=headers["admin"],
    )
    assert rule.status_code == 201, rule.text
    draft = client.post(
        "/api/v1/timetable/versions",
        json={
            "name": "Stale after fixed event",
            "academic_year": year,
            "week_start": "2026-10-19",
            "class_ids": [refs["instructional_class_id"]],
        },
        headers=headers["operator"],
    )
    assert draft.status_code == 201, draft.text
    event = client.post(
        BASE,
        json=_event(year, "Monday assembly", "CLASS", [refs["instructional_class_id"]]),
        headers=headers["admin"],
    )
    assert event.status_code == 201, event.text
    version = draft.json()
    placement = client.post(
        f"/api/v1/timetable/versions/{version['id']}/placements",
        json={
            "expected_revision": version["revision"],
            "lesson_requirement_id": requirement.json()["id"],
            "weekday": "TUE",
            "start_period": "P1",
            "period_count": 1,
            "note": "",
        },
        headers=headers["operator"],
    )
    assert placement.status_code == 409
    assert "configuration changed" in placement.json()["detail"].lower()


def test_class_and_teacher_fixed_events_block_manual_and_generated_lessons(lesson_context):
    client, headers, refs = lesson_context
    year = f"BLOCKED-{refs['instructional_class_id']}"
    requirement = client.post(
        "/api/v1/timetable/lessons",
        json={**refs, "academic_year": year, "weekly_count": 1, "block_length": 1},
        headers=headers["operator"],
    )
    assert requirement.status_code == 201, requirement.text
    rule = client.post(
        "/api/v1/timetable/rules",
        json={
            "academic_year": year,
            "target_type": "CLASS",
            "target_id": refs["instructional_class_id"],
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
            "rule": {},
        },
        headers=headers["admin"],
    )
    assert rule.status_code == 201, rule.text
    teacher_event = client.post(
        BASE,
        json=_event(year, "Teacher duty", "TEACHER", [refs["teacher_id"]], weekday="MON", slot="P1"),
        headers=headers["admin"],
    )
    assert teacher_event.status_code == 201, teacher_event.text
    class_event = client.post(
        BASE,
        json={
            "academic_year": year,
            "label": "Class activity",
            "audience_type": "CLASS",
            "target_mode": "SELECTED",
            "target_ids": [refs["instructional_class_id"]],
            "slots": [
                {"weekday": day, "slot_code": slot} for day in ("MON", "TUE", "WED", "THU", "FRI") for slot in ("P1", "P2", "P3", "P4")
            ],
        },
        headers=headers["admin"],
    )
    assert class_event.status_code == 201, class_event.text
    draft = client.post(
        "/api/v1/timetable/versions",
        json={
            "name": "Fixed event blockers",
            "academic_year": year,
            "week_start": "2026-10-19",
            "class_ids": [refs["instructional_class_id"]],
        },
        headers=headers["operator"],
    )
    assert draft.status_code == 201, draft.text
    version = draft.json()

    def place(day):
        return client.post(
            f"/api/v1/timetable/versions/{version['id']}/placements",
            json={
                "expected_revision": version["revision"],
                "lesson_requirement_id": requirement.json()["id"],
                "weekday": day,
                "start_period": "P1",
                "period_count": 1,
                "note": "",
            },
            headers=headers["operator"],
        )

    teacher_conflict = place("MON")
    assert teacher_conflict.status_code == 409
    assert "Teacher duty" in teacher_conflict.json()["detail"]
    class_conflict = place("TUE")
    assert class_conflict.status_code == 409
    assert "Class activity" in class_conflict.json()["detail"]
    generated = client.post(
        f"/api/v1/timetable/versions/{version['id']}/generate",
        json={"expected_revision": version["revision"], "mode": "FILL_PENDING"},
        headers=headers["operator"],
    )
    assert generated.status_code == 200, generated.text
    assert generated.json()["timetable"]["placements"] == []
    assert generated.json()["generation"]["unplaced"][0]["reason"] == "NO_LEGAL_POSITION"


def test_legacy_draft_snapshot_remains_compatible_only_without_new_events():
    snapshot = {"schema_version": 1, "classes": {"12": {"id": 12}}, "requirements": {}}
    current = {**snapshot, "schema_version": 2, "fixed_events": []}
    assert snapshots_match_current(snapshot, current)
    assert not snapshots_match_current(snapshot, {**current, "fixed_events": [{"id": 3}]})
