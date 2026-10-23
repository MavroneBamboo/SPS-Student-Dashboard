from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.crypto import decrypt_sensitive
from app.audit import record_event
from app.deps import Claims, DbSession, require_roles
from app.models import AttendanceRecord, AttendanceSession, Student
from app.schemas import AttendanceRecordCreate, AttendanceRecordResponse, AttendanceSessionCreate, AttendanceSessionResponse

router = APIRouter(prefix="/attendance", tags=["attendance"])


def session_response(row: AttendanceSession) -> AttendanceSessionResponse:
    return AttendanceSessionResponse(id=row.id, session_date=row.session_date, session_type=row.session_type, class_name=row.class_name, expected_count=row.expected_count, notes=row.notes, status=row.status)


def record_response(row: AttendanceRecord, student: Student) -> AttendanceRecordResponse:
    return AttendanceRecordResponse(id=row.id, session_id=row.session_id, pris_no=student.pris_no, student_name=decrypt_sensitive(student.name_encrypted) or "", attendance_status=row.attendance_status, correction_reason=row.correction_reason)


@router.post("/sessions", response_model=AttendanceSessionResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator"))])
def create_session(payload: AttendanceSessionCreate, db: DbSession, claims: Claims) -> AttendanceSessionResponse:
    if db.scalar(select(Student.id).where(Student.class_name == payload.class_name, Student.status == "ACTIVE")) is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Class has no eligible active students")
    row = AttendanceSession(session_date=payload.session_date, session_type=payload.session_type, class_name=payload.class_name.strip(), expected_count=payload.expected_count, notes=payload.notes, created_by=int(claims["sub"]))
    db.add(row)
    db.flush()
    record_event(db, int(claims["sub"]), "attendance.session.created", "attendance_session", str(row.id), {"class_name": row.class_name, "session_date": row.session_date.isoformat(), "session_type": row.session_type})
    db.commit()
    db.refresh(row)
    return session_response(row)


@router.get("/sessions", response_model=list[AttendanceSessionResponse])
def list_sessions(db: DbSession, claims: Claims) -> list[AttendanceSessionResponse]:
    rows = db.scalars(select(AttendanceSession).order_by(AttendanceSession.session_date.desc(), AttendanceSession.id.desc())).all()
    return [session_response(row) for row in rows]


@router.get("/sessions/{session_id}/records", response_model=list[AttendanceRecordResponse])
def list_records(session_id: int, db: DbSession, claims: Claims) -> list[AttendanceRecordResponse]:
    session = db.get(AttendanceSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance session not found")
    rows = db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id == session_id).order_by(AttendanceRecord.id)).all()
    return [record_response(row, db.get(Student, row.student_id)) for row in rows]


@router.post("/sessions/{session_id}/close", response_model=AttendanceSessionResponse, dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator"))])
def close_session(session_id: int, db: DbSession, claims: Claims) -> AttendanceSessionResponse:
    row = db.get(AttendanceSession, session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance session not found")
    row.status = "CLOSED"
    record_event(db, int(claims["sub"]), "attendance.session.closed", "attendance_session", str(row.id))
    db.commit()
    db.refresh(row)
    return session_response(row)


@router.post("/sessions/{session_id}/records", response_model=AttendanceRecordResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator"))])
def create_record(session_id: int, payload: AttendanceRecordCreate, db: DbSession, claims: Claims) -> AttendanceRecordResponse:
    session = db.get(AttendanceSession, session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance session not found")
    if session.status != "OPEN":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Attendance session is closed")
    student = db.scalar(select(Student).where(Student.pris_no == payload.pris_no.strip().upper(), Student.status == "ACTIVE"))
    if student is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Student is not active or does not exist")
    if student.class_name != session.class_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Student does not belong to the session class")
    if db.scalar(select(AttendanceRecord).where(AttendanceRecord.session_id == session_id, AttendanceRecord.student_id == student.id)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Attendance record already exists")
    row = AttendanceRecord(session_id=session_id, student_id=student.id, attendance_status=payload.attendance_status, correction_reason=payload.correction_reason, created_by=int(claims["sub"]), updated_by=int(claims["sub"]))
    db.add(row)
    db.flush()
    record_event(db, int(claims["sub"]), "attendance.record.created", "attendance_record", str(row.id), {"session_id": session_id, "student_id": student.id, "attendance_status": row.attendance_status})
    db.commit()
    db.refresh(row)
    return record_response(row, student)


@router.patch("/records/{record_id}", response_model=AttendanceRecordResponse, dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator"))])
def correct_record(record_id: int, payload: AttendanceRecordCreate, db: DbSession, claims: Claims) -> AttendanceRecordResponse:
    row = db.get(AttendanceRecord, record_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Attendance record not found")
    session = db.get(AttendanceSession, row.session_id)
    student = db.get(Student, row.student_id)
    if session.status != "OPEN":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Attendance session is closed")
    if payload.attendance_status != row.attendance_status and not payload.correction_reason:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Correction reason is required when changing attendance")
    previous_status = row.attendance_status
    row.attendance_status = payload.attendance_status
    row.correction_reason = payload.correction_reason
    row.updated_by = int(claims["sub"])
    record_event(db, int(claims["sub"]), "attendance.record.corrected", "attendance_record", str(row.id), {"from": previous_status, "to": row.attendance_status, "reason": payload.correction_reason})
    db.commit()
    db.refresh(row)
    return record_response(row, student)
