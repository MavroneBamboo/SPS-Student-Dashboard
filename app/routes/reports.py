import calendar
import csv
import io
import json
from datetime import UTC, date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response, StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import func, select

from app.crypto import decrypt_sensitive
from app.deps import Claims, DbSession, require_roles
from app.models import AttendanceRecord, AttendanceRosterEntry, AttendanceSession, AuditEvent, Student

router = APIRouter(prefix="/reports", tags=["reports"])

READ_ROLES = ("Superuser", "Operator", "Executive")


@router.get("/dashboard", dependencies=[Depends(require_roles(*READ_ROLES))])
def dashboard(
    db: DbSession,
    claims: Claims,
    class_name: str | None = Query(default=None, max_length=120),
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    student_query = select(Student)
    if class_name:
        student_query = student_query.where(Student.class_name == class_name)
    students = db.scalars(student_query).all()
    active_students = [student for student in students if student.status == "ACTIVE"]
    by_class: dict[str, int] = {}
    by_category: dict[str, int] = {}
    for student in active_students:
        by_class[student.class_name] = by_class.get(student.class_name, 0) + 1
        by_category[student.category] = by_category.get(student.category, 0) + 1

    session_query = select(AttendanceSession)
    if class_name:
        session_query = session_query.where(AttendanceSession.class_name == class_name)
    if date_from:
        session_query = session_query.where(AttendanceSession.session_date >= date_from)
    if date_to:
        session_query = session_query.where(AttendanceSession.session_date <= date_to)
    sessions = db.scalars(session_query.order_by(AttendanceSession.session_date)).all()
    session_ids = [session.id for session in sessions]
    counts: dict[int, dict[str, int]] = {}
    if session_ids:
        for session_id, attendance_status, count in db.execute(
            select(AttendanceRecord.session_id, AttendanceRecord.attendance_status, func.count())
            .where(AttendanceRecord.session_id.in_(session_ids))
            .group_by(AttendanceRecord.session_id, AttendanceRecord.attendance_status)
        ):
            counts.setdefault(session_id, {})[attendance_status] = int(count)
    expected = sum(session.expected_count for session in sessions)
    present = sum(values.get("PRESENT", 0) + values.get("LATE", 0) for values in counts.values())
    recorded = sum(sum(values.values()) for values in counts.values())
    missing = sum(
        max(0, session.expected_count - sum(counts.get(session.id, {}).values())) + counts.get(session.id, {}).get("MISSING", 0)
        for session in sessions
    )
    trend = []
    for session in sessions:
        statuses = counts.get(session.id, {})
        session_present = statuses.get("PRESENT", 0) + statuses.get("LATE", 0)
        trend.append(
            {
                "date": session.session_date.isoformat(),
                "class": session.class_name,
                "session": session.session_type,
                "present_or_late": session_present,
                "recorded": sum(statuses.values()),
                "expected": session.expected_count,
                "rate": round(100 * session_present / session.expected_count, 1) if session.expected_count else 0,
            }
        )
    return {
        "filters": {
            "class_name": class_name,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
        "refreshed_at": datetime.now(UTC).isoformat(),
        "students": {
            "active": len(active_students),
            "by_class": dict(sorted(by_class.items())),
            "by_category": dict(sorted(by_category.items())),
        },
        "attendance": {
            "sessions": len(sessions),
            "expected": expected,
            "recorded": recorded,
            "missing": missing,
            "present_or_late": present,
            "rate": round(100 * present / expected, 1) if expected else None,
            "trend": trend,
        },
    }


@router.get("/attendance.csv", dependencies=[Depends(require_roles(*READ_ROLES))])
def attendance_csv(
    db: DbSession,
    claims: Claims,
    class_name: str | None = Query(default=None, max_length=120),
    date_from: date | None = None,
    date_to: date | None = None,
) -> StreamingResponse:
    query = (
        select(AttendanceSession, AttendanceRecord, AttendanceRosterEntry)
        .join(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id)
        .join(
            AttendanceRosterEntry,
            (AttendanceRosterEntry.session_id == AttendanceRecord.session_id)
            & (AttendanceRosterEntry.student_id == AttendanceRecord.student_id),
        )
        .order_by(AttendanceSession.session_date, AttendanceSession.class_name, AttendanceRosterEntry.pris_no_snapshot)
    )
    if class_name:
        query = query.where(AttendanceSession.class_name == class_name)
    if date_from:
        query = query.where(AttendanceSession.session_date >= date_from)
    if date_to:
        query = query.where(AttendanceSession.session_date <= date_to)
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["Session date", "Session", "Class", "Pris No.", "Student", "Attendance"])
    for session, record, roster_entry in db.execute(query):
        writer.writerow(
            [
                session.session_date.isoformat(),
                session.session_type,
                session.class_name,
                roster_entry.pris_no_snapshot,
                decrypt_sensitive(roster_entry.student_name_encrypted) or "",
                record.attendance_status,
            ]
        )
    return StreamingResponse(
        iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=attendance-report.csv"}
    )


@router.get("/attendance/monthly.xlsx", dependencies=[Depends(require_roles(*READ_ROLES))])
def attendance_monthly_xlsx(
    db: DbSession,
    claims: Claims,
    month: str = Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
    class_name: str = Query(min_length=1, max_length=120),
) -> Response:
    year, month_number = (int(part) for part in month.split("-"))
    first_day = date(year, month_number, 1)
    last_day = date(year, month_number, calendar.monthrange(year, month_number)[1])
    sessions = db.scalars(
        select(AttendanceSession)
        .where(
            AttendanceSession.class_name == class_name,
            AttendanceSession.session_date >= first_day,
            AttendanceSession.session_date <= last_day,
        )
        .order_by(AttendanceSession.session_date, AttendanceSession.id)
    ).all()
    sessions_by_id = {session.id: session for session in sessions}
    roster_entries: dict[int, AttendanceRosterEntry] = {}
    if sessions_by_id:
        for entry in db.scalars(
            select(AttendanceRosterEntry)
            .where(AttendanceRosterEntry.session_id.in_(sessions_by_id))
            .order_by(AttendanceRosterEntry.session_id, AttendanceRosterEntry.id)
        ).all():
            roster_entries.setdefault(entry.student_id, entry)
    else:
        # Preserve a useful blank register when no attendance sessions have
        # been entered for the requested month; label this nonhistorical basis.
        for student in db.scalars(
            select(Student).where(Student.class_name == class_name, Student.status == "ACTIVE").order_by(Student.pris_no)
        ).all():
            roster_entries[student.id] = AttendanceRosterEntry(
                student_id=student.id,
                pris_no_snapshot=student.pris_no,
                student_name_encrypted=student.name_encrypted,
                student_status=student.status,
            )
    attendance: dict[tuple[int, int, str], str] = {}
    if sessions_by_id and roster_entries:
        records = db.execute(
            select(AttendanceRecord, AttendanceRosterEntry)
            .join(
                AttendanceRosterEntry,
                (AttendanceRosterEntry.session_id == AttendanceRecord.session_id)
                & (AttendanceRosterEntry.student_id == AttendanceRecord.student_id),
            )
            .where(AttendanceRecord.session_id.in_(sessions_by_id))
        )
        status_codes = {"PRESENT": "P", "ABSENT": "A", "LATE": "L", "EXCUSED": "E", "MISSING": "M"}
        for record, _roster_entry in records:
            session = sessions_by_id[record.session_id]
            slots = ("AM", "PM") if session.session_type == "FULL_DAY" else (("AM",) if session.session_type == "MORNING" else ("PM",))
            for slot in slots:
                attendance[(record.student_id, session.session_date.day, slot)] = status_codes[record.attendance_status]

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Monthly Attendance"

    def write_literal(row: int, column: int, value: str) -> None:
        cell = sheet.cell(row, column, value)
        cell.data_type = "s"

    days_in_month = calendar.monthrange(year, month_number)[1]
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=3 + days_in_month * 2)
    sheet.cell(1, 1, f"MONTHLY ATTENDANCE | {first_day.strftime('%B %Y')}")
    sheet.cell(2, 1, "CLASS")
    write_literal(2, 3, class_name)
    legacy_sessions = [session for session in sessions if session.roster_snapshot_state != "CAPTURED"]
    if legacy_sessions:
        roster_note = "Roster source: captured entries; legacy rosters include recorded students only and migration-time names."
    elif sessions:
        roster_note = "Roster source: session snapshots."
    else:
        roster_note = "Roster source: current active profiles; no sessions exist in this month."
    sheet.cell(3, 1, roster_note)
    sheet.cell(4, 1, "STATUS")
    sheet.cell(4, 2, "PRIS NO.")
    sheet.cell(4, 3, "NAME")
    header_fill = PatternFill("solid", fgColor="17365D")
    header_font = Font(color="FFFFFF", bold=True)
    for column in range(1, 4):
        cell = sheet.cell(4, column)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")
    for day in range(1, days_in_month + 1):
        first_col = 4 + (day - 1) * 2
        sheet.merge_cells(start_row=3, start_column=first_col, end_row=3, end_column=first_col + 1)
        sheet.cell(3, first_col, date(year, month_number, day))
        sheet.cell(3, first_col).number_format = "ddd, d mmm"
        for slot, column in (("AM", first_col), ("PM", first_col + 1)):
            cell = sheet.cell(4, column, slot)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
    ordered_roster = sorted(roster_entries.values(), key=lambda entry: entry.pris_no_snapshot)
    for row_number, entry in enumerate(ordered_roster, start=5):
        write_literal(row_number, 1, entry.student_status or "")
        write_literal(row_number, 2, entry.pris_no_snapshot)
        write_literal(row_number, 3, decrypt_sensitive(entry.student_name_encrypted) or "")
        for day in range(1, days_in_month + 1):
            for slot_index, slot in enumerate(("AM", "PM")):
                column = 4 + (day - 1) * 2 + slot_index
                code = attendance.get((entry.student_id, day, slot))
                if code:
                    sheet.cell(row_number, column, code)
    sheet.freeze_panes = "D5"
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 12
    sheet.column_dimensions["B"].width = 16
    sheet.column_dimensions["C"].width = 30
    for column in range(4, 4 + days_in_month * 2):
        sheet.column_dimensions[get_column_letter(column)].width = 5
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A3
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.print_title_rows = "1:4"
    sheet.print_area = f"A1:{get_column_letter(3 + days_in_month * 2)}{max(4, 4 + len(ordered_roster))}"
    output = io.BytesIO()
    workbook.save(output)
    safe_class = quote(class_name.strip().replace(" ", "_"), safe="")
    filename = f"attendance-{year}-{month_number:02d}-{safe_class}.xlsx"
    return Response(
        output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit", dependencies=[Depends(require_roles("Superuser", "IT Administrator"))])
def audit_events(db: DbSession, claims: Claims, limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    rows = db.scalars(select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).limit(limit)).all()
    return [
        {
            "id": row.id,
            "actor_id": row.actor_id,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "details": json.loads(row.details_json),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
