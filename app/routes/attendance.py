from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.class_names import normalize_class_name
from app.crypto import decrypt_sensitive
from app.deps import Claims, DbSession, require_roles
from app.models import (
    AttendanceClassMapping,
    AttendanceRecord,
    AttendanceRosterEntry,
    AttendanceSession,
    InstructionalClass,
    Student,
    TimetableSlot,
    TimetableVersion,
)
from app.schemas import (
    AttendanceRecordCorrection,
    AttendanceRecordCreate,
    AttendanceRecordResponse,
    AttendanceRosterEntryResponse,
    AttendanceSessionClose,
    AttendanceSessionCount,
    AttendanceSessionCreate,
    AttendanceSessionReopen,
    AttendanceSessionResponse,
)

router = APIRouter(prefix="/attendance", tags=["attendance"], dependencies=[Depends(require_roles("Operator", "Superuser"))])


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
        roster_snapshot_state=row.roster_snapshot_state,
        timetable_version_id=row.timetable_version_id,
        instructional_class_id=row.instructional_class_id,
    )


def record_response(row: AttendanceRecord, roster_entry: AttendanceRosterEntry, session: AttendanceSession) -> AttendanceRecordResponse:
    return AttendanceRecordResponse(
        id=row.id,
        version=row.version,
        session_version=session.version,
        session_id=row.session_id,
        pris_no=roster_entry.pris_no_snapshot,
        student_name=decrypt_sensitive(roster_entry.student_name_encrypted) or "",
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
        record_response(record, roster_entry, session)
        for record, roster_entry in db.execute(
            select(AttendanceRecord, AttendanceRosterEntry)
            .join(
                AttendanceRosterEntry,
                (AttendanceRosterEntry.session_id == AttendanceRecord.session_id)
                & (AttendanceRosterEntry.student_id == AttendanceRecord.student_id),
            )
            .where(AttendanceRecord.session_id == session.id)
            .order_by(AttendanceRosterEntry.pris_no_snapshot)
        )
    ]


def _roster(db: DbSession, session: AttendanceSession) -> list[AttendanceRosterEntryResponse]:
    recorded = {
        row.student_id: row.attendance_status
        for row in db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id == session.id)).all()
    }
    return [
        AttendanceRosterEntryResponse(
            student_id=entry.student_id,
            pris_no=entry.pris_no_snapshot,
            student_name=decrypt_sensitive(entry.student_name_encrypted) or "",
            student_status=entry.student_status,
            attendance_status=recorded.get(entry.student_id),
        )
        for entry in db.scalars(
            select(AttendanceRosterEntry)
            .where(AttendanceRosterEntry.session_id == session.id)
            .order_by(AttendanceRosterEntry.pris_no_snapshot)
        ).all()
    ]


def _lock_and_validate_session_period(db: DbSession, payload: AttendanceSessionCreate) -> None:
    normalized_class = payload.class_name.strip().upper()
    if db.bind.dialect.name == "postgresql":
        lock_key = f"attendance-session:{normalized_class}:{payload.session_date.isoformat()}"
        db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(lock_key, 0))))
    existing = db.scalars(
        select(AttendanceSession)
        .where(
            func.upper(func.trim(AttendanceSession.class_name)) == normalized_class,
            AttendanceSession.session_date == payload.session_date,
        )
        .with_for_update()
    ).all()
    if any(
        row.session_type == payload.session_type or row.session_type == "FULL_DAY" or payload.session_type == "FULL_DAY" for row in existing
    ):
        raise HTTPException(status_code=409, detail="An attendance session already exists for an overlapping class, date and period")


@router.post("/sessions", response_model=AttendanceSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(payload: AttendanceSessionCreate, db: DbSession, claims: Claims) -> AttendanceSessionResponse:
    _lock_and_validate_session_period(db, payload)
    provenance = (payload.timetable_version_id, payload.instructional_class_id)
    mapped_class_key = None
    if (provenance[0] is None) != (provenance[1] is None):
        raise HTTPException(status_code=422, detail="Published timetable and instructional class must be provided together")
    if provenance[0] is not None:
        version = db.scalar(
            select(TimetableVersion).where(TimetableVersion.id == provenance[0], TimetableVersion.is_published.is_(True)).with_for_update()
        )
        if version is None:
            raise HTTPException(status_code=409, detail="The selected timetable is no longer published")
        week_start = payload.session_date.fromordinal(payload.session_date.toordinal() - payload.session_date.weekday())
        if version.week_start != week_start:
            raise HTTPException(status_code=422, detail="The selected timetable does not cover the session date")
        weekday = ("MON", "TUE", "WED", "THU", "FRI")[payload.session_date.weekday()] if payload.session_date.weekday() < 5 else None
        if weekday is None:
            raise HTTPException(status_code=422, detail="Published instructional timetable sessions are available Monday to Friday")
        mapping = db.scalar(
            select(AttendanceClassMapping).where(
                AttendanceClassMapping.instructional_class_id == provenance[1],
                AttendanceClassMapping.is_active.is_(True),
            )
        )
        if mapping is None:
            raise HTTPException(status_code=422, detail="Create an active attendance class mapping before using this timetable class")
        try:
            _, class_key = normalize_class_name(payload.class_name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if class_key != mapping.class_key:
            raise HTTPException(status_code=422, detail="Session class does not match the published timetable class mapping")
        mapped_class_key = mapping.class_key
        if not db.scalar(
            select(TimetableSlot.id)
            .where(
                TimetableSlot.version_id == version.id,
                TimetableSlot.instructional_class_id == provenance[1],
                TimetableSlot.weekday == weekday,
            )
            .limit(1)
        ):
            raise HTTPException(status_code=422, detail="The published timetable has no lessons for this class on the session date")
    student_query = select(Student).where(Student.status == "ACTIVE")
    if mapped_class_key is None:
        student_query = student_query.where(Student.class_name == payload.class_name)
    else:
        candidate_names = db.scalars(select(Student.class_name).where(Student.status == "ACTIVE").distinct()).all()
        matching_names = []
        for candidate_name in candidate_names:
            try:
                _, candidate_key = normalize_class_name(candidate_name)
            except ValueError:
                continue
            if candidate_key == mapped_class_key:
                matching_names.append(candidate_name)
        student_query = student_query.where(Student.class_name.in_(matching_names))
    eligible = db.scalars(student_query.order_by(Student.pris_no).with_for_update()).all()
    if not eligible:
        raise HTTPException(status_code=422, detail="Class has no eligible active students")
    actor_id = int(claims["sub"])
    row = AttendanceSession(
        **payload.model_dump(),
        created_by=actor_id,
        status="OPEN",
        version=1,
        roster_snapshot_state="CAPTURED",
    )
    try:
        db.add(row)
        db.flush()
        db.add_all(
            [
                AttendanceRosterEntry(
                    session_id=row.id,
                    student_id=student.id,
                    pris_no_snapshot=student.pris_no,
                    student_name_encrypted=student.name_encrypted,
                    student_status=student.status,
                    created_by=actor_id,
                )
                for student in eligible
            ]
        )
        db.flush()
        record_event(
            db,
            int(claims["sub"]),
            "attendance.session.created",
            "attendance_session",
            str(row.id),
            {
                "class_name": row.class_name,
                "session_date": row.session_date.isoformat(),
                "session_type": row.session_type,
                "version": 1,
                "roster_count": len(eligible),
                "roster_snapshot_state": row.roster_snapshot_state,
                "timetable_version_id": row.timetable_version_id,
                "instructional_class_id": row.instructional_class_id,
            },
        )
        result = session_response(row)
        db.commit()
        return result
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="An attendance session already exists for an overlapping class, date and period"
        ) from exc


@router.get("/scheduled-classes")
def list_scheduled_classes(
    db: DbSession,
    claims: Claims,
    session_date: date,
    academic_year: str = Query(min_length=1, max_length=20),
) -> list[dict]:
    week_start = session_date.fromordinal(session_date.toordinal() - session_date.weekday())
    version = db.scalar(
        select(TimetableVersion).where(
            TimetableVersion.academic_year == academic_year.strip().upper(),
            TimetableVersion.week_start == week_start,
            TimetableVersion.is_published.is_(True),
        )
    )
    if version is None or session_date.weekday() >= 5:
        return []
    weekday = ("MON", "TUE", "WED", "THU", "FRI")[session_date.weekday()]
    rows = db.execute(
        select(TimetableSlot.instructional_class_id, func.count(TimetableSlot.id))
        .where(TimetableSlot.version_id == version.id, TimetableSlot.weekday == weekday)
        .group_by(TimetableSlot.instructional_class_id)
    ).all()
    if not rows:
        return []
    class_ids = [class_id for class_id, _ in rows]
    classes = {row.id: row for row in db.scalars(select(InstructionalClass).where(InstructionalClass.id.in_(class_ids))).all()}
    mappings = {
        row.instructional_class_id: row
        for row in db.scalars(
            select(AttendanceClassMapping).where(
                AttendanceClassMapping.instructional_class_id.in_(class_ids),
                AttendanceClassMapping.is_active.is_(True),
            )
        ).all()
    }
    counts = db.execute(
        select(Student.class_name, func.count(Student.id)).where(Student.status == "ACTIVE").group_by(Student.class_name)
    ).all()
    student_counts: dict[str, int] = {}
    for name, count in counts:
        try:
            _, key = normalize_class_name(name)
        except ValueError:
            continue
        student_counts[key] = student_counts.get(key, 0) + count
    result = []
    for instructional_class_id, slot_count in rows:
        mapping = mappings.get(instructional_class_id)
        if mapping is None:
            continue
        instructional_class = classes.get(instructional_class_id)
        if instructional_class is None:
            continue
        result.append(
            {
                "timetable_version_id": version.id,
                "academic_year": version.academic_year,
                "week_start": version.week_start.isoformat(),
                "instructional_class_id": instructional_class.id,
                "instructional_class_code": instructional_class.code,
                "instructional_class_name": instructional_class.name,
                "class_name": mapping.student_class_name,
                "active_students": student_counts.get(mapping.class_key, 0),
                "lesson_count": slot_count,
            }
        )
    return sorted(result, key=lambda item: (item["instructional_class_code"], item["class_name"].casefold()))


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
    roster = _roster(db, session)
    return {
        "session": session_response(session),
        "records": records,
        "roster": roster,
        "roster_count": len(roster),
        "roster_snapshot_complete": session.roster_snapshot_state == "CAPTURED",
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


@router.post("/sessions/{session_id}/reopen", response_model=AttendanceSessionResponse)
def reopen_session(session_id: int, payload: AttendanceSessionReopen, db: DbSession, claims: Claims) -> AttendanceSessionResponse:
    row = _session(db, session_id)
    if row.status != "CLOSED":
        raise HTTPException(status_code=409, detail="Only a closed attendance session can be reopened")
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Attendance changed; reload the session before reopening")
    changed = db.execute(
        update(AttendanceSession)
        .where(
            AttendanceSession.id == session_id, AttendanceSession.version == payload.expected_version, AttendanceSession.status == "CLOSED"
        )
        .values(version=payload.expected_version + 1, status="OPEN")
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Attendance changed; reload the session before reopening")
    db.refresh(row)
    record_event(
        db,
        int(claims["sub"]),
        "attendance.session.reopened",
        "attendance_session",
        str(row.id),
        {"previous_version": payload.expected_version, "version": row.version, "reason": payload.reason},
    )
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
    student = db.scalar(select(Student).where(Student.pris_no == payload.pris_no.upper()).with_for_update())
    if student is None:
        raise HTTPException(status_code=422, detail="Student does not exist")
    roster_entry = db.scalar(
        select(AttendanceRosterEntry).where(
            AttendanceRosterEntry.session_id == session_id,
            AttendanceRosterEntry.student_id == student.id,
        )
    )
    if roster_entry is None:
        raise HTTPException(status_code=422, detail="Student is not on this attendance session's roster snapshot")
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
        result = record_response(row, roster_entry, session)
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
    roster_entry = db.scalar(
        select(AttendanceRosterEntry).where(
            AttendanceRosterEntry.session_id == session.id,
            AttendanceRosterEntry.student_id == existing.student_id,
        )
    )
    if payload.pris_no.upper() != roster_entry.pris_no_snapshot:
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
    result = record_response(existing, roster_entry, session)
    db.commit()
    return result
