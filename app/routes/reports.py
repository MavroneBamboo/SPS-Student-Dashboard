import csv
import io
import json
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select

from app.crypto import decrypt_sensitive
from app.deps import Claims, DbSession, require_roles
from app.models import AttendanceRecord, AttendanceSession, AuditEvent, Student

router = APIRouter(prefix="/reports", tags=["reports"])

READ_ROLES = ("Superuser", "IT Administrator", "Operator", "Executive")


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
        select(AttendanceSession, AttendanceRecord, Student)
        .join(AttendanceRecord, AttendanceRecord.session_id == AttendanceSession.id)
        .join(Student, Student.id == AttendanceRecord.student_id)
        .order_by(AttendanceSession.session_date, AttendanceSession.class_name, Student.pris_no)
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
    for session, record, student in db.execute(query):
        writer.writerow(
            [
                session.session_date.isoformat(),
                session.session_type,
                session.class_name,
                student.pris_no,
                decrypt_sensitive(student.name_encrypted) or "",
                record.attendance_status,
            ]
        )
    return StreamingResponse(
        iter([stream.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=attendance-report.csv"}
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
