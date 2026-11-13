from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime
from io import BytesIO
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from app.audit import record_event
from app.deps import Claims, DbSession, require_roles
from app.models import AuditEvent, TimetableVersion
from app.routes.timetables import _get, _view

router = APIRouter(
    prefix="/timetable/versions",
    tags=["timetable reports"],
    dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator", "Executive"))],
)

WEEKDAYS = (("MON", "Monday"), ("TUE", "Tuesday"), ("WED", "Wednesday"), ("THU", "Thursday"), ("FRI", "Friday"))
MIME_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _sort_period(period: dict) -> tuple[int, str]:
    return period["display_order"], period["slot_code"]


def _safe_text(value: object) -> object:
    if isinstance(value, str) and value.lstrip(" \t\r\n")[:1] in {"=", "+", "-", "@"}:
        return f"'{value}"
    return value


def _fixed_event(snapshot: dict, audience_type: str, target_id: int, weekday: str, slot_code: str) -> str:
    event = next(
        (
            event
            for event in snapshot.get("fixed_events", [])
            if event["audience_type"] == audience_type
            and target_id in event["target_ids"]
            and any(slot["weekday"] == weekday and slot["slot_code"] == slot_code for slot in event["slots"])
        ),
        None,
    )
    return event["label"] if event else ""


def _workbook(view: dict, kinds: tuple[str, ...], audit_event: AuditEvent) -> bytes:
    snapshot = view["snapshot"]
    classes = sorted(snapshot["classes"].values(), key=lambda item: (item["reporting_order"], item["code"]))
    teachers = sorted(snapshot["teachers"].values(), key=lambda item: (item["short_code"], item["full_name"]))
    requirements = snapshot["requirements"]
    subjects = snapshot["subjects"]
    teacher_by_id = snapshot["teachers"]
    class_by_id = snapshot["classes"]

    occupied: dict[tuple[str, str, str], dict] = {}
    for placement in view["placements"]:
        requirement = requirements[str(placement["lesson_requirement_id"])]
        subject = subjects[str(requirement["subject_id"])]
        teacher = teacher_by_id[str(requirement["teacher_id"])]
        class_item = class_by_id[str(requirement["instructional_class_id"])]
        for slot in placement["slots"]:
            occupied[(str(class_item["id"]), slot["weekday"], slot["slot_code"])] = {
                "subject": subject,
                "teacher": teacher,
                "class": class_item,
                "slot": slot,
                "note": placement["note"],
                "placement_id": placement["id"],
            }

    workbook = Workbook()
    workbook.remove(workbook.active)
    metadata = workbook.create_sheet("Version")
    metadata.append(["Timetable report metadata", ""])
    for label, value in (
        ("Version ID", view["id"]),
        ("Name", view["name"]),
        ("Academic year", view["academic_year"]),
        ("Week starting", view["week_start"].isoformat()),
        ("Status", view["status"]),
        ("Revision", view["revision"]),
        ("Created at", view["created_at"].isoformat() if view["created_at"] else ""),
        ("Approved at", view["approved_at"].isoformat() if view["approved_at"] else ""),
        (
            "Exported at UTC",
            audit_event.created_at.astimezone(UTC).isoformat() if audit_event.created_at else datetime.now(UTC).isoformat(),
        ),
        ("Audit event ID", audit_event.id),
        ("Audit action", audit_event.action),
        ("Export actor ID", audit_event.actor_id),
    ):
        metadata.append([label, value])
    if "class" in kinds:
        sheet = workbook.create_sheet("By InstClass")
        sheet.append(
            [
                "Class code",
                "Instructional class",
                "Weekday",
                "Period",
                "Start",
                "End",
                "Subject",
                "Teacher code",
                "Teacher name",
                "Lesson note",
                "Placement ID",
                "Fixed event",
            ]
        )
        for class_item in classes:
            periods = sorted(class_item["periods"], key=_sort_period)
            for weekday_code, weekday_name in WEEKDAYS:
                for period in periods:
                    if period["is_schedulable"]:
                        placed = occupied.get((str(class_item["id"]), weekday_code, period["slot_code"]))
                    else:
                        placed = None
                    subject = placed["subject"] if placed else None
                    teacher = placed["teacher"] if placed else None
                    slot = placed["slot"] if placed else {}
                    sheet.append(
                        [
                            class_item["code"],
                            class_item["name"],
                            weekday_name,
                            period["label"],
                            slot.get("starts_at", period.get("starts_at")),
                            slot.get("ends_at", period.get("ends_at")),
                            subject["code"] if subject else ("Lunch / Muster" if not period["is_schedulable"] else ""),
                            teacher["short_code"] if teacher else "",
                            teacher["full_name"] if teacher else "",
                            placed["note"] if placed else "",
                            placed["placement_id"] if placed else "",
                            _fixed_event(snapshot, "CLASS", class_item["id"], weekday_code, period["slot_code"])
                            if placed is None and period["is_schedulable"]
                            else "",
                        ]
                    )

    if "teacher" in kinds:
        sheet = workbook.create_sheet("By Teacher")
        sheet.append(
            [
                "Teacher code",
                "Teacher name",
                "Weekday",
                "Period",
                "Start",
                "End",
                "Availability",
                "Subject",
                "Class code",
                "Instructional class",
                "Lesson note",
                "Placement ID",
                "Fixed event",
            ]
        )
        teacher_periods: dict[int, dict[tuple[str, str, str, str], dict]] = defaultdict(dict)
        for class_item in classes:
            for period in class_item["periods"]:
                key = (period["slot_code"], period["label"], period.get("starts_at") or "", period.get("ends_at") or "")
                for teacher in teachers:
                    teacher_periods[teacher["id"]][key] = period

        for teacher in teachers:
            ordered_periods = sorted(teacher_periods[teacher["id"]].values(), key=_sort_period)
            for weekday_code, weekday_name in WEEKDAYS:
                availability = teacher["availability"].get(weekday_code, [])
                for period in ordered_periods:
                    assignments = [
                        placed
                        for (class_id, day, slot_code), placed in occupied.items()
                        if day == weekday_code
                        and slot_code == period["slot_code"]
                        and (
                            teacher["id"] == placed["teacher"]["id"]
                            or teacher["id"] in placed["teacher"].get("participant_ids", [placed["teacher"]["id"]])
                        )
                        and placed["slot"]["starts_at"] == period.get("starts_at")
                        and placed["slot"]["ends_at"] == period.get("ends_at")
                    ]
                    placed = assignments[0] if assignments else None
                    class_item = placed["class"] if placed else None
                    slot = placed["slot"] if placed else {}
                    subject = placed["subject"] if placed else None
                    fixed_event = _fixed_event(snapshot, "TEACHER", teacher["id"], weekday_code, period["slot_code"])
                    if not period["is_schedulable"]:
                        state = "Lunch / Muster"
                    else:
                        state = (
                            "Scheduled" if placed else (fixed_event or ("Free" if period["slot_code"] in availability else "Unavailable"))
                        )
                    sheet.append(
                        [
                            teacher["short_code"],
                            teacher["full_name"],
                            weekday_name,
                            period["label"],
                            slot.get("starts_at", period.get("starts_at")),
                            slot.get("ends_at", period.get("ends_at")),
                            state,
                            subject["code"] if subject else "",
                            class_item["code"] if class_item else "",
                            class_item["name"] if class_item else "",
                            placed["note"] if placed else "",
                            placed["placement_id"] if placed else "",
                            fixed_event if placed is None and period["is_schedulable"] else "",
                        ]
                    )

    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for row in sheet.iter_rows():
            for cell in row:
                if isinstance(cell.value, str):
                    cell.value = _safe_text(cell.value)
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="17365D")
            cell.alignment = Alignment(wrap_text=True, vertical="center")
        sheet.row_dimensions[1].height = 32
        for column in sheet.columns:
            values = list(column)
            width = min(42, max(12, max(len(str(cell.value or "")) for cell in values) + 2))
            sheet.column_dimensions[get_column_letter(column[0].column)].width = width
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


@router.get("/{version_id}/reports.xlsx")
def timetable_report_xlsx(
    version_id: int,
    db: DbSession,
    claims: Claims,
    kind: Literal["class", "teacher", "both"] = "both",
) -> Response:
    version: TimetableVersion = _get(db, version_id, claims)
    view = _view(db, version)
    kinds = ("class", "teacher") if kind == "both" else (kind,)
    event = record_event(
        db,
        int(claims["sub"]),
        "timetable.report.exported",
        "timetable_version",
        str(version.id),
        {"kind": kind, "format": "xlsx", "revision": view["revision"], "status": view["status"]},
    )
    db.flush()
    content = _workbook(view, kinds, event)
    db.commit()
    safe_year = re.sub(r"[^A-Za-z0-9._-]", "_", version.academic_year)
    filename = f"timetable-{safe_year}-{version.week_start.isoformat()}-{kind}.xlsx"
    return Response(
        content=content,
        media_type=MIME_XLSX,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )
