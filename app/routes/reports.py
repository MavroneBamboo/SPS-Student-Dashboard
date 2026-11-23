import calendar
import csv
import io
import json
from datetime import UTC, date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response, StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import case, func, select

from app.audit import record_event
from app.crypto import decrypt_sensitive
from app.deps import Claims, DbSession, require_roles
from app.models import AttendanceRecord, AttendanceRosterEntry, AttendanceSession, AuditEvent, Student, User
from app.observability import current_request_id

router = APIRouter(prefix="/reports", tags=["reports"])

READ_ROLES = ("Superuser", "Operator", "Executive")


@router.get("/dashboard", dependencies=[Depends(require_roles(*READ_ROLES))])
def dashboard(
    db: DbSession,
    claims: Claims,
    class_name: str | None = Query(default=None, max_length=120),
    institution: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None, max_length=40),
    status: str = Query(default="ACTIVE", pattern="^(ACTIVE|INACTIVE|ALL)$"),
    academic_year: str | None = Query(default=None, max_length=20),
    date_from: date | None = None,
    date_to: date | None = None,
) -> dict:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="date_from must be on or before date_to")
    profile_filters = []
    if class_name:
        profile_filters.append(Student.class_name == class_name.strip())
    if institution:
        profile_filters.append(Student.institution == institution.strip())
    if category:
        profile_filters.append(Student.category == category.strip())
    if academic_year:
        profile_filters.append(Student.academic_year == academic_year.strip())
    profile_scope_filters = list(profile_filters)
    active_filters = [*profile_filters, Student.status == "ACTIVE"]
    if status != "ALL":
        profile_filters.append(Student.status == status)

    def grouped_counts(column) -> dict[str, int]:
        return {
            (key if key is not None else "Unassigned"): int(count)
            for key, count in db.execute(select(column, func.count()).select_from(Student).where(*profile_filters).group_by(column))
        }

    matching_profiles = int(db.scalar(select(func.count()).select_from(Student).where(*profile_filters)) or 0)
    active_profiles = int(db.scalar(select(func.count()).select_from(Student).where(*active_filters)) or 0)
    by_class = grouped_counts(Student.class_name)
    by_category = grouped_counts(Student.category)
    by_institution = grouped_counts(Student.institution)
    age_counts = db.execute(
        select(
            func.sum(case((Student.age_in_academic_year <= 21, 1), else_=0)),
            func.sum(case((Student.age_in_academic_year > 21, 1), else_=0)),
            func.sum(case((Student.age_in_academic_year.is_(None), 1), else_=0)),
        )
        .select_from(Student)
        .where(*profile_filters)
    ).one()

    def as_utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)

    session_filters = []
    if class_name:
        session_filters.append(AttendanceSession.class_name == class_name.strip())
    if date_from:
        session_filters.append(AttendanceSession.session_date >= date_from)
    if date_to:
        session_filters.append(AttendanceSession.session_date <= date_to)
    session_rows = db.execute(
        select(
            AttendanceSession.session_date.label("session_date"),
            AttendanceSession.session_type.label("session_type"),
            AttendanceSession.class_name.label("class_name"),
            AttendanceSession.expected_count.label("expected_count"),
            AttendanceSession.updated_at.label("session_updated_at"),
            func.count(AttendanceRecord.id).label("recorded_count"),
            func.sum(
                case(
                    (AttendanceRecord.attendance_status.in_(("PRESENT", "LATE")), 1),
                    else_=0,
                )
            ).label("present_or_late"),
            func.sum(case((AttendanceRecord.attendance_status == "MISSING", 1), else_=0)).label("explicit_missing"),
            func.max(AttendanceRecord.updated_at).label("record_updated_at"),
        )
        .select_from(AttendanceSession)
        .outerjoin(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id)
        .where(*session_filters)
        .group_by(
            AttendanceSession.id,
            AttendanceSession.session_date,
            AttendanceSession.session_type,
            AttendanceSession.class_name,
            AttendanceSession.expected_count,
            AttendanceSession.updated_at,
        )
        .order_by(AttendanceSession.session_date, AttendanceSession.id)
    ).all()
    expected = sum(row.expected_count for row in session_rows)
    present = sum(int(row.present_or_late or 0) for row in session_rows)
    recorded = sum(row.recorded_count for row in session_rows)
    missing = sum(max(0, row.expected_count - row.recorded_count) + int(row.explicit_missing or 0) for row in session_rows)
    trend = []
    for row in session_rows:
        session_present = int(row.present_or_late or 0)
        session_recorded = row.recorded_count
        trend.append(
            {
                "date": row.session_date.isoformat(),
                "class": row.class_name,
                "session": row.session_type,
                "present_or_late": session_present,
                "recorded": session_recorded,
                "expected": row.expected_count,
                "rate": round(100 * session_present / row.expected_count, 1) if row.expected_count else 0,
            }
        )

    data_profile_filters = active_filters if status == "ACTIVE" else profile_scope_filters
    if status == "INACTIVE":
        data_profile_filters = [*profile_scope_filters, Student.status.in_(("ACTIVE", "INACTIVE"))]
    profile_data_through = as_utc(db.scalar(select(func.max(Student.updated_at)).where(*data_profile_filters)))
    record_data_through = max((as_utc(row.record_updated_at) for row in session_rows if row.record_updated_at is not None), default=None)
    session_data_through = max((as_utc(row.session_updated_at) for row in session_rows if row.session_updated_at is not None), default=None)
    attendance_timestamps = [value for value in (session_data_through, record_data_through) if value is not None]
    attendance_data_through = max(attendance_timestamps, default=None)
    data_timestamps = [value for value in (profile_data_through, attendance_data_through) if value is not None]
    data_through = max(data_timestamps, default=None)
    refreshed_at = datetime.now(UTC)
    return {
        "filters": {
            "class_name": class_name.strip() if class_name else None,
            "institution": institution.strip() if institution else None,
            "category": category.strip() if category else None,
            "status": status,
            "academic_year": academic_year.strip() if academic_year else None,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
        "refreshed_at": refreshed_at.isoformat(),
        "requested_by": claims["username"],
        "profile_data_through_at": profile_data_through.isoformat() if profile_data_through else None,
        "attendance_data_through_at": attendance_data_through.isoformat() if attendance_data_through else None,
        "data_through_at": data_through.isoformat() if data_through else None,
        "students": {
            "active": active_profiles,
            "matching": matching_profiles,
            "by_class": dict(sorted(by_class.items())),
            "by_category": dict(sorted(by_category.items())),
            "by_institution": dict(sorted(by_institution.items())),
            "by_age_band": {
                "21 and under": int(age_counts[0] or 0),
                "Over 21": int(age_counts[1] or 0),
                "Age not recorded": int(age_counts[2] or 0),
            },
        },
        "attendance": {
            "sessions": len(session_rows),
            "expected": expected,
            "recorded": recorded,
            "missing": missing,
            "present_or_late": present,
            "rate": round(100 * present / expected, 1) if expected else None,
            "trend": trend,
        },
    }


@router.get("/dashboard.xlsx", dependencies=[Depends(require_roles(*READ_ROLES))])
def dashboard_xlsx(
    db: DbSession,
    claims: Claims,
    class_name: str | None = Query(default=None, max_length=120),
    institution: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None, max_length=40),
    status: str = Query(default="ACTIVE", pattern="^(ACTIVE|INACTIVE|ALL)$"),
    academic_year: str | None = Query(default=None, max_length=20),
    date_from: date | None = None,
    date_to: date | None = None,
) -> Response:
    result = dashboard(
        db,
        claims,
        class_name=class_name,
        institution=institution,
        category=category,
        status=status,
        academic_year=academic_year,
        date_from=date_from,
        date_to=date_to,
    )
    workbook = Workbook()
    overview = workbook.active
    overview.title = "Overview"
    profile_sheet = workbook.create_sheet("Profile breakdowns")
    attendance_sheet = workbook.create_sheet("Attendance sessions")

    def append_row(sheet, values: list[str | int | float | None]) -> None:
        is_empty = sheet.max_row == 1 and sheet.max_column == 1 and sheet.cell(1, 1).value is None
        row_number = 1 if is_empty else sheet.max_row + 1
        for column_number, value in enumerate(values, start=1):
            cell = sheet.cell(row_number, column_number, value)
            if isinstance(value, str):
                cell.data_type = "s"

    append_row(overview, ["SPS Student Dashboard | Filtered report"])
    append_row(overview, ["Generated at (UTC)", result["refreshed_at"]])
    append_row(overview, ["Data through (UTC)", result["data_through_at"] or "No matching source records"])
    append_row(overview, ["Profile data through (UTC)", result["profile_data_through_at"] or "No matching profile records"])
    append_row(overview, ["Attendance data through (UTC)", result["attendance_data_through_at"] or "No matching attendance records"])
    append_row(overview, ["Generated by", result["requested_by"]])
    append_row(overview, ["Profile status scope", status])
    for key, value in result["filters"].items():
        append_row(overview, [f"Filter: {key}", value if value is not None else "All"])
    append_row(overview, ["Matching student profiles", result["students"]["matching"]])
    append_row(overview, ["Active profiles in selected non-status scope", result["students"]["active"]])
    append_row(overview, ["Attendance rate (%)", result["attendance"]["rate"]])
    append_row(overview, ["Attendance sessions", result["attendance"]["sessions"]])
    append_row(overview, ["Expected attendance records", result["attendance"]["expected"]])
    append_row(overview, ["Recorded attendance records", result["attendance"]["recorded"]])
    append_row(overview, ["Missing attendance records", result["attendance"]["missing"]])

    append_row(profile_sheet, ["Breakdown", "Value", "Count"])
    for breakdown_name in ("by_class", "by_category", "by_institution", "by_age_band"):
        for value, count in result["students"][breakdown_name].items():
            append_row(profile_sheet, [breakdown_name.removeprefix("by_"), value, count])

    append_row(
        attendance_sheet,
        ["Session date", "Class", "Session", "Present / late", "Recorded", "Expected", "Rate (%)"],
    )
    for session in result["attendance"]["trend"]:
        append_row(
            attendance_sheet,
            [
                session["date"],
                session["class"],
                session["session"],
                session["present_or_late"],
                session["recorded"],
                session["expected"],
                session["rate"],
            ],
        )

    header_fill = PatternFill("solid", fgColor="17365D")
    header_font = Font(color="FFFFFF", bold=True)
    for sheet in workbook.worksheets:
        sheet.freeze_panes = "A2"
        sheet.sheet_view.showGridLines = False
        sheet.column_dimensions["A"].width = 34
        sheet.column_dimensions["B"].width = 36
        sheet.column_dimensions["C"].width = 18
        for cell in sheet[1]:
            cell.fill = header_fill
            cell.font = header_font
    overview.column_dimensions["A"].width = 48
    profile_sheet.auto_filter.ref = profile_sheet.dimensions
    attendance_sheet.auto_filter.ref = attendance_sheet.dimensions

    output = io.BytesIO()
    workbook.save(output)
    audit = AuditEvent(
        actor_id=int(claims["sub"]),
        action="report.dashboard.exported",
        entity_type="DASHBOARD_REPORT",
        entity_id="filtered-excel",
        request_id=current_request_id(),
        details_json=json.dumps(
            {
                "filters": result["filters"],
                "matching_profiles": result["students"]["matching"],
                "attendance_sessions": result["attendance"]["sessions"],
            },
            sort_keys=True,
        ),
    )
    db.add(audit)
    db.commit()
    filename = f"dashboard-{date.today().isoformat()}.xlsx"
    return Response(
        output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
    record_count = 0
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
        record_count += 1
    record_event(
        db,
        int(claims["sub"]),
        "report.attendance.exported",
        "ATTENDANCE_REPORT",
        "csv",
        {
            "format": "csv",
            "filters": {
                "class_name": class_name,
                "date_from": date_from.isoformat() if date_from else None,
                "date_to": date_to.isoformat() if date_to else None,
            },
            "record_count": record_count,
        },
    )
    db.commit()
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
    record_count = 0
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
            record_count += 1
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
    sheet.cell(1, 1, "MONTH")
    sheet.cell(1, 3, first_day)
    sheet.cell(1, 3).number_format = "mmmm yyyy"
    sheet.cell(2, 1, "CLASS")
    write_literal(2, 3, class_name)
    legacy_sessions = [session for session in sessions if session.roster_snapshot_state != "CAPTURED"]
    if legacy_sessions:
        roster_note = "Roster source: captured entries; legacy rosters include recorded students only and migration-time names."
    elif sessions:
        roster_note = "Roster source: session snapshots."
    else:
        roster_note = "Roster source: current active profiles; no sessions exist in this month."
    sheet.merge_cells(start_row=3, start_column=1, end_row=3, end_column=3)
    sheet.cell(3, 1, roster_note)
    sheet.cell(3, 1).alignment = Alignment(vertical="center", wrap_text=True)
    for column, value in ((1, "STATUS"), (2, "PRIS NO."), (3, "NAME")):
        sheet.merge_cells(start_row=4, start_column=column, end_row=5, end_column=column)
        cell = sheet.cell(4, column, value)
        cell.fill = PatternFill("solid", fgColor="17365D")
        cell.font = Font(color="FFFFFF", bold=True)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    header_fill = PatternFill("solid", fgColor="17365D")
    header_font = Font(color="FFFFFF", bold=True)
    for day in range(1, days_in_month + 1):
        first_col = 4 + (day - 1) * 2
        day_date = date(year, month_number, day)
        sheet.merge_cells(start_row=3, start_column=first_col, end_row=3, end_column=first_col + 1)
        weekday = sheet.cell(3, first_col, day_date.strftime("%a").upper())
        weekday.alignment = Alignment(horizontal="center", vertical="center")
        weekday.fill = PatternFill("solid", fgColor="D9EAF7")
        sheet.merge_cells(start_row=4, start_column=first_col, end_row=4, end_column=first_col + 1)
        day_header = sheet.cell(4, first_col, day_date)
        day_header.number_format = "d mmm"
        day_header.alignment = Alignment(horizontal="center", vertical="center")
        day_header.fill = header_fill
        day_header.font = header_font
        for slot, column in (("AM", first_col), ("PM", first_col + 1)):
            cell = sheet.cell(5, column, slot)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center")
    ordered_roster = sorted(roster_entries.values(), key=lambda entry: entry.pris_no_snapshot)
    for row_number, entry in enumerate(ordered_roster, start=6):
        write_literal(row_number, 1, entry.student_status or "")
        write_literal(row_number, 2, entry.pris_no_snapshot)
        write_literal(row_number, 3, decrypt_sensitive(entry.student_name_encrypted) or "")
        for day in range(1, days_in_month + 1):
            for slot_index, slot in enumerate(("AM", "PM")):
                column = 4 + (day - 1) * 2 + slot_index
                code = attendance.get((entry.student_id, day, slot))
                if code:
                    sheet.cell(row_number, column, code)
    sheet.freeze_panes = "D6"
    sheet.sheet_view.showGridLines = False
    sheet.column_dimensions["A"].width = 12
    sheet.column_dimensions["B"].width = 16
    sheet.column_dimensions["C"].width = 30
    for column in range(4, 4 + days_in_month * 2):
        sheet.column_dimensions[get_column_letter(column)].width = 5
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 2
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_margins.left = 0.2
    sheet.page_margins.right = 0.2
    sheet.page_margins.top = 0.25
    sheet.page_margins.bottom = 0.25
    sheet.print_title_rows = "1:5"
    sheet.print_area = f"A1:{get_column_letter(3 + days_in_month * 2)}{max(5, 5 + len(ordered_roster))}"
    output = io.BytesIO()
    workbook.save(output)
    roster_source = (
        "legacy_partial_session_snapshots" if legacy_sessions else ("session_snapshots" if sessions else "current_active_profiles")
    )
    record_event(
        db,
        int(claims["sub"]),
        "report.attendance.exported",
        "ATTENDANCE_REPORT",
        "monthly.xlsx",
        {
            "format": "monthly.xlsx",
            "filters": {"month": month, "class_name": class_name},
            "session_count": len(sessions),
            "roster_count": len(ordered_roster),
            "record_count": record_count,
            "roster_source": roster_source,
        },
    )
    db.commit()
    safe_class = quote(class_name.strip().replace(" ", "_"), safe="")
    filename = f"attendance-{year}-{month_number:02d}-{safe_class}.xlsx"
    return Response(
        output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/audit", dependencies=[Depends(require_roles("Superuser", "IT Administrator"))])
def audit_events(
    db: DbSession,
    claims: Claims,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    action: str | None = Query(default=None, min_length=1, max_length=80),
    entity_type: str | None = Query(default=None, min_length=1, max_length=80),
    actor_id: int | None = Query(default=None, ge=1),
) -> list[dict]:
    query = select(AuditEvent, User.username).outerjoin(User, User.id == AuditEvent.actor_id)
    if action:
        query = query.where(AuditEvent.action == action.strip())
    if entity_type:
        query = query.where(AuditEvent.entity_type == entity_type.strip())
    if actor_id is not None:
        query = query.where(AuditEvent.actor_id == actor_id)
    rows = db.execute(query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc()).offset(offset).limit(limit)).all()
    return [
        {
            "id": row.id,
            "actor_id": row.actor_id,
            "actor_username": username,
            "action": row.action,
            "entity_type": row.entity_type,
            "entity_id": row.entity_id,
            "request_id": row.request_id,
            "details": json.loads(row.details_json),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row, username in rows
    ]
