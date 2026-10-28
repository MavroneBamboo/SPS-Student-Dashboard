from io import BytesIO

from openpyxl import load_workbook


def _report_context(lesson_context):
    client, headers, references = lesson_context
    year = f"EXPORT-{references['instructional_class_id']}"
    requirement = client.post(
        "/api/v1/timetable/lessons",
        json={**references, "academic_year": year, "weekly_count": 4, "block_length": 2},
        headers=headers["operator"],
    )
    assert requirement.status_code == 201, requirement.text
    rule = client.post(
        "/api/v1/timetable/rules",
        json={
            "academic_year": year,
            "target_type": "CLASS",
            "target_id": references["instructional_class_id"],
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
            "name": "Export verification",
            "academic_year": year,
            "week_start": "2026-10-19",
            "class_ids": [references["instructional_class_id"]],
        },
        headers=headers["operator"],
    )
    assert draft.status_code == 201, draft.text
    for day in ("MON", "TUE"):
        version = draft.json()
        placed = client.post(
            f"/api/v1/timetable/versions/{version['id']}/placements",
            json={
                "expected_revision": version["revision"],
                "lesson_requirement_id": requirement.json()["id"],
                "weekday": day,
                "start_period": "P1",
                "period_count": 2,
                "note": f"{day} note",
            },
            headers=headers["operator"],
        )
        assert placed.status_code == 201, placed.text
        draft = placed
    return client, headers, draft.json()


def test_timetable_xlsx_exports_snapshot_sheets_and_audits_without_mutating_version(lesson_context):
    client, headers, version = _report_context(lesson_context)
    response = client.get(f"/api/v1/timetable/versions/{version['id']}/reports.xlsx?kind=both", headers=headers["operator"])
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert f"timetable-{version['academic_year']}-2026-10-19-both.xlsx" in response.headers["content-disposition"]

    workbook = load_workbook(BytesIO(response.content), data_only=True)
    assert workbook.sheetnames == ["Version", "By InstClass", "By Teacher"]
    metadata = list(workbook["Version"].values)
    assert ("Audit event ID",) in [row[:1] for row in metadata]
    assert any(row[0] == "Revision" and row[1] == version["revision"] for row in metadata)
    class_rows = list(workbook["By InstClass"].values)
    teacher_rows = list(workbook["By Teacher"].values)
    assert class_rows[0][:4] == ("Class code", "Instructional class", "Weekday", "Period")
    assert any(row[2:4] == ("Monday", "Period 1") and row[6] for row in class_rows[1:])
    assert any(row[3] == "Lunch" and row[6] == "Lunch / Muster" for row in class_rows[1:])
    assert any(row[2:4] == ("Monday", "Period 1") and row[6] == "Scheduled" for row in teacher_rows[1:])
    assert any(row[2:4] == ("Monday", "Period 3") and row[6] == "Free" for row in teacher_rows[1:])

    current = client.get(f"/api/v1/timetable/versions/{version['id']}", headers=headers["operator"]).json()
    assert current["revision"] == version["revision"]
    assert current["placements"] == version["placements"]
    events = client.get("/api/v1/reports/audit?limit=500", headers=headers["admin"]).json()
    exported = [event for event in events if event["action"] == "timetable.report.exported" and event["entity_id"] == str(version["id"])]
    assert exported[-1]["details"] == {"format": "xlsx", "kind": "both", "revision": version["revision"], "status": "DRAFT"}


def test_executive_can_export_only_approved_timetable(lesson_context):
    client, headers, version = _report_context(lesson_context)
    path = f"/api/v1/timetable/versions/{version['id']}/reports.xlsx"
    assert client.get(path, headers=headers["executive"]).status_code == 404
    approved = client.post(
        f"/api/v1/timetable/versions/{version['id']}/approve",
        json={"expected_revision": version["revision"]},
        headers=headers["admin"],
    )
    assert approved.status_code == 200, approved.text
    exported = client.get(path + "?kind=teacher", headers=headers["executive"])
    assert exported.status_code == 200
    assert load_workbook(BytesIO(exported.content), read_only=True).sheetnames == ["Version", "By Teacher"]
