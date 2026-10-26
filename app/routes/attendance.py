from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.crypto import decrypt_sensitive
from app.deps import Claims, DbSession, require_roles
from app.models import AttendanceRecord, AttendanceSession, Student
from app.schemas import (
    AttendanceRecordCorrection,
    AttendanceRecordCreate,
    AttendanceRecordResponse,
    AttendanceSessionClose,
    AttendanceSessionCount,
    AttendanceSessionCreate,
    AttendanceSessionResponse,
)

router = APIRouter(prefix="/attendance", tags=["attendance"], dependencies=[Depends(require_roles("Operator"))])


def session_response(row: AttendanceSession) -> AttendanceSessionResponse:
    return AttendanceSessionResponse(
        id=row.id,
        version=row.version,
        session_date=row.session_date,
        session_type=row.session_type,
        class_name=row.class_name,
        expected_count=row.expected_count,
        notes=row.notes,
        status=row.status,
    )


def record_response(row: AttendanceRecord, student: Student, session: AttendanceSession) -> AttendanceRecordResponse:
    return AttendanceRecordResponse(
        id=row.id,
        version=row.version,
        session_version=session.version,
        session_id=row.session_id,
        pris_no=student.pris_no,
        student_name=decrypt_sensitive(student.name_encrypted) or "",
        attendance_status=row.attendance_status,
        correction_reason=row.correction_reason,
    )


def _session(db: DbSession, session_id: int, expected_version: int | None = None) -> AttendanceSession:
    row = db.scalar(
        select(AttendanceSession).where(AttendanceSession.id == session_id).with_for_update().execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Attendance session not found")
    if expected_version is not None:
        if row.status != "OPEN":
            raise HTTPException(status_code=409, detail="Attendance session is closed")
        if row.version != expected_version:
            raise HTTPException(status_code=409, detail="Attendance changed; reload the session before saving")
    return row


def _advance(db: DbSession, session: AttendanceSession, expected_version: int) -> None:
    changed = db.execute(
        update(AttendanceSession)
        .where(AttendanceSession.id == session.id, AttendanceSession.version == expected_version, AttendanceSession.status == "OPEN")
        .values(version=expected_version + 1)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Attendance changed; reload the session before saving")
    db.refresh(session)


def _records(db: DbSession, session: AttendanceSession) -> list[AttendanceRecordResponse]:
    return [
        record_response(record, student, session)
        for record, student in db.execute(
            select(AttendanceRecord, Student)
            .join(Student, Student.id == AttendanceRecord.student_id)
            .where(AttendanceRecord.session_id == session.id)
            .order_by(Student.pris_no)
        )
    ]


@router.post("/sessions", response_model=AttendanceSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(payload: AttendanceSessionCreate, db: DbSession, claims: Claims) -> AttendanceSessionResponse:
    if db.scalar(select(Student.id).where(Student.class_name == payload.class_name, Student.status == "ACTIVE")) is None:
        raise HTTPException(status_code=422, detail="Class has no eligible active students")
    row = AttendanceSession(**payload.model_dump(), created_by=int(claims["sub"]), status="OPEN", version=1)
    try:
        db.add(row)
        db.flush()
        record_event(
            db,
            int(claims["sub"]),
            "attendance.session.created",
            "attendance_session",
            str(row.id),
            {"class_name": row.class_name, "session_date": row.session_date.isoformat(), "session_type": row.session_type, "version": 1},
        )
        result = session_response(row)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A session already exists for this class, date and session type") from exc


@router.get("/sessions", response_model=list[AttendanceSessionResponse])
def list_sessions(
    db: DbSession,
    claims: Claims,
    class_name: str | None = Query(default=None, max_length=120),
    date_from: date | None = None,
    date_to: date | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> list[AttendanceSessionResponse]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="Session start date must be on or before end date")
    query = select(AttendanceSession)
    if class_name:
        query = query.where(AttendanceSession.class_name == class_name.strip())
    if date_from:
        query = query.where(AttendanceSession.session_date >= date_from)
    if date_to:
        query = query.where(AttendanceSession.session_date <= date_to)
    return [
        session_response(row)
        for row in db.scalars(
            query.order_by(AttendanceSession.session_date.desc(), AttendanceSession.id.desc()).offset(offset).limit(limit)
        ).all()
    ]


@router.get("/sessions/{session_id}")
def get_session(session_id: int, db: DbSession, claims: Claims) -> dict:
    session = _session(db, session_id)
    records = _records(db, session)
    return {
        "session": session_response(session),
        "records": records,
        "missing": max(0, session.expected_count - len(records)),
        "marked_missing": sum(row.attendance_status == "MISSING" for row in records),
    }


@router.get("/sessions/{session_id}/records", response_model=list[AttendanceRecordResponse])
def list_records(session_id: int, db: DbSession, claims: Claims) -> list[AttendanceRecordResponse]:
    return _records(db, _session(db, session_id))


@router.post("/sessions/{session_id}/close", response_model=AttendanceSessionResponse)
def close_session(session_id: int, payload: AttendanceSessionClose, db: DbSession, claims: Claims) -> AttendanceSessionResponse:
    row = _session(db, session_id, payload.expected_version)
    records = _records(db, row)
    missing = max(0, row.expected_count - len(records))
    marked_missing = sum(record.attendance_status == "MISSING" for record in records)
    if (missing or marked_missing) and not payload.allow_incomplete:
        raise HTTPException(
            status_code=409, detail="Attendance is incomplete; record all attendance or explicitly close incomplete with a reason"
        )
    _advance(db, row, payload.expected_version)
    row.status = "CLOSED"
    record_event(
        db,
        int(claims["sub"]),
        "attendance.session.closed",
        "attendance_session",
        str(row.id),
        {
            "previous_version": payload.expected_version,
            "version": row.version,
            "missing": missing,
            "marked_missing": marked_missing,
            "allow_incomplete": payload.allow_incomplete,
            "reason": payload.reason,
        },
    )
    db.flush()
    result = session_response(row)
    db.commit()
    return result


@router.patch("/sessions/{session_id}", response_model=AttendanceSessionResponse)
def change_expected_count(session_id: int, payload: AttendanceSessionCount, db: DbSession, claims: Claims) -> AttendanceSessionResponse:
    row = _session(db, session_id, payload.expected_version)
    recorded = db.scalar(select(func.count()).select_from(AttendanceRecord).where(AttendanceRecord.session_id == session_id)) or 0
    if payload.expected_count < recorded:
        raise HTTPException(status_code=409, detail="Expected count cannot be lower than the number of recorded students")
    previous = row.expected_count
    _advance(db, row, payload.expected_version)
    row.expected_count = payload.expected_count
    record_event(
        db,
        int(claims["sub"]),
        "attendance.session.count_changed",
        "attendance_session",
        str(row.id),
        {"before": previous, "after": row.expected_count, "reason": payload.reason, "version": row.version},
    )
    db.flush()
    result = session_response(row)
    db.commit()
    return result


@router.post("/sessions/{session_id}/records", response_model=AttendanceRecordResponse, status_code=status.HTTP_201_CREATED)
def create_record(session_id: int, payload: AttendanceRecordCreate, db: DbSession, claims: Claims) -> AttendanceRecordResponse:
    session = _session(db, session_id, payload.expected_session_version)
    student = db.scalar(select(Student).where(Student.pris_no == payload.pris_no.upper(), Student.status == "ACTIVE").with_for_update())
    if student is None:
        raise HTTPException(status_code=422, detail="Student is not active or does not exist")
    if student.class_name != session.class_name:
        raise HTTPException(status_code=422, detail="Student does not belong to the session class")
    if db.scalar(select(AttendanceRecord.id).where(AttendanceRecord.session_id == session_id, AttendanceRecord.student_id == student.id)):
        raise HTTPException(status_code=409, detail="Attendance record already exists")
    if (
        db.scalar(select(func.count()).select_from(AttendanceRecord).where(AttendanceRecord.session_id == session_id))
        >= session.expected_count
    ):
        raise HTTPException(
            status_code=409, detail="Session expected count is already reached; reconcile the session before adding records"
        )
    _advance(db, session, payload.expected_session_version)
    row = AttendanceRecord(
        session_id=session_id,
        student_id=student.id,
        attendance_status=payload.attendance_status,
        correction_reason=payload.correction_reason,
        created_by=int(claims["sub"]),
        updated_by=int(claims["sub"]),
        version=1,
    )
    try:
        db.add(row)
        db.flush()
        record_event(
            db,
            int(claims["sub"]),
            "attendance.record.created",
            "attendance_record",
            str(row.id),
            {
                "session_id": session_id,
                "student_id": student.id,
                "attendance_status": row.attendance_status,
                "session_version": session.version,
                "version": row.version,
            },
        )
        result = record_response(row, student, session)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Attendance record conflicts with stored attendance") from exc


@router.patch("/records/{record_id}", response_model=AttendanceRecordResponse)
def correct_record(record_id: int, payload: AttendanceRecordCorrection, db: DbSession, claims: Claims) -> AttendanceRecordResponse:
    existing = db.get(AttendanceRecord, record_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Attendance record not found")
    session = _session(db, existing.session_id, payload.expected_session_version)
    db.refresh(existing)
    if existing.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Attendance record changed; reload before correcting")
    student = db.get(Student, existing.student_id)
    if payload.pris_no.upper() != student.pris_no:
        raise HTTPException(status_code=422, detail="A correction cannot change the attendance student")
    previous = {
        "attendance_status": existing.attendance_status,
        "correction_reason": existing.correction_reason,
        "version": existing.version,
    }
    _advance(db, session, payload.expected_session_version)
    changed = db.execute(
        update(AttendanceRecord)
        .where(AttendanceRecord.id == record_id, AttendanceRecord.version == payload.expected_version)
        .values(
            attendance_status=payload.attendance_status,
            correction_reason=payload.correction_reason,
            updated_by=int(claims["sub"]),
            version=payload.expected_version + 1,
        )
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Attendance record changed; reload before correcting")
    db.refresh(existing)
    record_event(
        db,
        int(claims["sub"]),
        "attendance.record.corrected",
        "attendance_record",
        str(existing.id),
        {
            "before": previous,
            "after": {
                "attendance_status": existing.attendance_status,
                "correction_reason": existing.correction_reason,
                "version": existing.version,
            },
            "session_version": session.version,
        },
    )
    db.flush()
    result = record_response(existing, student, session)
    db.commit()
    return result
