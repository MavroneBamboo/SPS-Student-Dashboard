import json
from io import BytesIO
from uuid import uuid4

from openpyxl import load_workbook

from app.db import SessionLocal
from app.models import AuditEvent


def test_dashboard_export_is_filtered_aggregate_audited_and_formula_safe(lesson_context):
    client, headers, _ = lesson_context
    suffix = uuid4().hex[:8].upper()
    class_name = f"=REPORT-{suffix}"
    category_response = client.post(
        "/api/v1/student-reference/categories",
        json={"code": f"EXP-{suffix}", "name": "Export category"},
        headers=headers["admin"],
    )
    assert category_response.status_code == 201, category_response.text
    category = category_response.json()
    created = client.post(
        "/api/v1/students",
        json={
            "pris_no": f"EXPORT-{suffix}",
            "name": "Private Export Student",
            "class_name": class_name,
            "category": category["code"],
            "status": "ACTIVE",
            "academic_year": "2026",
            "age_in_academic_year": 28,
        },
        headers=headers["operator"],
    )
    assert created.status_code == 201, created.text

    response = client.get(
        "/api/v1/reports/dashboard.xlsx",
        params={"class_name": class_name, "academic_year": "2026"},
        headers=headers["executive"],
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    workbook = load_workbook(BytesIO(response.content), data_only=True)
    assert workbook.sheetnames == ["Dashboard Summary", "Student Breakdowns", "Attendance Sessions"]
    summary = list(workbook["Dashboard Summary"].values)
    assert ("Matching profiles", 1) in summary
    assert ("Active students", 1) in summary
    assert ("Class Name", class_name) in summary
    breakdown = list(workbook["Student Breakdowns"].values)
    assert ("Class", class_name, 1) in breakdown
    assert ("Category", category["code"], 1) in breakdown
    assert ("Academic year · age", "2026 · 28", 1) in breakdown
    assert all(
        "Private Export Student" not in str(value) and f"EXPORT-{suffix}" not in str(value)
        for row in summary + breakdown
        for value in row
        if value is not None
    )
    assert workbook["Student Breakdowns"]["B2"].data_type == "s"
    assert list(workbook["Attendance Sessions"].values)[1][0] == "No attendance sessions match the selected filters."

    with SessionLocal() as db:
        event = db.query(AuditEvent).filter_by(action="report.dashboard.exported", entity_id=summary[1][1]).one()
        assert event.actor_id > 0
        assert json.loads(event.details_json)["filters"]["class_name"] == class_name


def test_dashboard_export_is_denied_to_it_and_rejects_reversed_date_ranges(lesson_context):
    client, headers, _ = lesson_context
    assert client.get("/api/v1/reports/dashboard.xlsx", headers=headers["admin"]).status_code == 403
    assert (
        client.get("/api/v1/reports/dashboard.xlsx?date_from=2026-11-03&date_to=2026-11-02", headers=headers["executive"]).status_code
        == 422
    )
