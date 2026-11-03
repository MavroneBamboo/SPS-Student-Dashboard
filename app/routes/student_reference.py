from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.class_names import normalize_class_name
from app.deps import Claims, DbSession, require_roles
from app.models import AttendanceClassMapping, InstructionalClass, Student, StudentClassMapping
from app.schemas import (
    AttendanceClassMappingCreate,
    AttendanceClassMappingResponse,
    AttendanceClassMappingUpdate,
    StudentClassMappingCreate,
    StudentClassMappingResponse,
    StudentClassMappingUpdate,
)
from app.student_class_mapping import normalize_source_class_label

router = APIRouter(prefix="/student-reference/class-mappings", tags=["student reference data"])
READ_ACCESS = Depends(require_roles("Operator", "IT Administrator", "Superuser"))
EDIT_ACCESS = Depends(require_roles("IT Administrator", "Superuser"))


def _mapping_response(db: DbSession, mapping: StudentClassMapping) -> StudentClassMappingResponse:
    instructional_class = db.get(InstructionalClass, mapping.instructional_class_id)
    if instructional_class is None:
        raise HTTPException(status_code=409, detail="Mapped instructional class no longer exists")
    return StudentClassMappingResponse(
        id=mapping.id,
        source_workbook=mapping.source_workbook,
        source_label=mapping.source_label,
        instructional_class_id=instructional_class.id,
        class_code=instructional_class.code,
        class_name=instructional_class.name,
        is_active=mapping.is_active,
        version=mapping.version,
    )


def _active_class(db: DbSession, instructional_class_id: int) -> InstructionalClass:
    instructional_class = db.scalar(select(InstructionalClass).where(InstructionalClass.id == instructional_class_id).with_for_update())
    if instructional_class is None or not instructional_class.is_active:
        raise HTTPException(status_code=422, detail="Select an active instructional class")
    return instructional_class


@router.get("", response_model=list[StudentClassMappingResponse], dependencies=[READ_ACCESS])
def list_student_class_mappings(db: DbSession, claims: Claims) -> list[StudentClassMappingResponse]:
    rows = db.scalars(select(StudentClassMapping).order_by(StudentClassMapping.source_workbook, StudentClassMapping.source_key)).all()
    return [_mapping_response(db, row) for row in rows]


@router.post("", response_model=StudentClassMappingResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_student_class_mapping(payload: StudentClassMappingCreate, db: DbSession, claims: Claims) -> StudentClassMappingResponse:
    try:
        label, key = normalize_source_class_label(payload.source_label)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _active_class(db, payload.instructional_class_id)
    if db.scalar(
        select(StudentClassMapping.id).where(
            StudentClassMapping.source_workbook == payload.source_workbook,
            StudentClassMapping.source_key == key,
        )
    ):
        raise HTTPException(status_code=409, detail="A mapping already exists for this workbook class label")
    row = StudentClassMapping(
        source_workbook=payload.source_workbook,
        source_label=label,
        source_key=key,
        instructional_class_id=payload.instructional_class_id,
        created_by=int(claims["sub"]),
    )
    db.add(row)
    try:
        db.flush()
        record_event(
            db,
            int(claims["sub"]),
            "student.class_mapping.created",
            "student_class_mapping",
            str(row.id),
            {
                "source_workbook": row.source_workbook,
                "source_label": row.source_label,
                "instructional_class_id": row.instructional_class_id,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A mapping already exists for this workbook class label") from exc
    db.refresh(row)
    return _mapping_response(db, row)


@router.patch("/{mapping_id}", response_model=StudentClassMappingResponse, dependencies=[EDIT_ACCESS])
def update_student_class_mapping(
    mapping_id: int, payload: StudentClassMappingUpdate, db: DbSession, claims: Claims
) -> StudentClassMappingResponse:
    row = db.get(StudentClassMapping, mapping_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Class mapping not found")
    values = payload.model_dump(exclude={"expected_version"}, exclude_unset=True)
    if "instructional_class_id" in values:
        _active_class(db, values["instructional_class_id"])
    values = {key: value for key, value in values.items() if value != getattr(row, key)}
    if not values:
        raise HTTPException(status_code=422, detail="Mapping update contains no change")
    old_version = row.version
    changed = db.execute(
        update(StudentClassMapping)
        .where(StudentClassMapping.id == mapping_id, StudentClassMapping.version == payload.expected_version)
        .values(**values, version=StudentClassMapping.version + 1)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Class mapping changed; reload it before saving")
    record_event(
        db,
        int(claims["sub"]),
        "student.class_mapping.updated",
        "student_class_mapping",
        str(mapping_id),
        {"fields": sorted(values), "previous_version": old_version, "version": old_version + 1},
    )
    db.commit()
    db.expire_all()
    return _mapping_response(db, db.get(StudentClassMapping, mapping_id))


attendance_mapping_router = APIRouter(prefix="/student-reference/attendance-class-mappings", tags=["attendance class mappings"])


def _active_student_counts(db: DbSession) -> dict[str, int]:
    counts: dict[str, int] = {}
    rows = db.execute(select(Student.class_name, func.count(Student.id)).where(Student.status == "ACTIVE").group_by(Student.class_name))
    for name, count in rows:
        try:
            _, key = normalize_class_name(name)
        except ValueError:
            continue
        counts[key] = counts.get(key, 0) + count
    return counts


def _attendance_mapping_response(
    db: DbSession, mapping: AttendanceClassMapping, counts: dict[str, int] | None = None
) -> AttendanceClassMappingResponse:
    instructional_class = db.get(InstructionalClass, mapping.instructional_class_id)
    if instructional_class is None:
        raise HTTPException(status_code=409, detail="Mapped instructional class no longer exists")
    return AttendanceClassMappingResponse(
        id=mapping.id,
        student_class_name=mapping.student_class_name,
        instructional_class_id=instructional_class.id,
        class_code=instructional_class.code,
        instructional_class_name=instructional_class.name,
        active_students=(counts if counts is not None else _active_student_counts(db)).get(mapping.class_key, 0),
        is_active=mapping.is_active,
        version=mapping.version,
    )


@attendance_mapping_router.get("", response_model=list[AttendanceClassMappingResponse], dependencies=[READ_ACCESS])
def list_attendance_class_mappings(db: DbSession, claims: Claims) -> list[AttendanceClassMappingResponse]:
    rows = db.scalars(select(AttendanceClassMapping).order_by(AttendanceClassMapping.class_key)).all()
    counts = _active_student_counts(db)
    return [_attendance_mapping_response(db, row, counts) for row in rows]


@attendance_mapping_router.post(
    "", response_model=AttendanceClassMappingResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS]
)
def create_attendance_class_mapping(payload: AttendanceClassMappingCreate, db: DbSession, claims: Claims) -> AttendanceClassMappingResponse:
    try:
        label, key = normalize_class_name(payload.student_class_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _active_class(db, payload.instructional_class_id)
    if db.scalar(
        select(AttendanceClassMapping.id).where(
            AttendanceClassMapping.is_active.is_(True),
            (AttendanceClassMapping.class_key == key) | (AttendanceClassMapping.instructional_class_id == payload.instructional_class_id),
        )
    ):
        raise HTTPException(status_code=409, detail="Student class or instructional class already has an attendance mapping")
    row = AttendanceClassMapping(
        student_class_name=label,
        class_key=key,
        instructional_class_id=payload.instructional_class_id,
        created_by=int(claims["sub"]),
    )
    db.add(row)
    try:
        db.flush()
        record_event(
            db,
            int(claims["sub"]),
            "attendance.class_mapping.created",
            "attendance_class_mapping",
            str(row.id),
            {"student_class_name": row.student_class_name, "instructional_class_id": row.instructional_class_id},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Student class or instructional class already has an attendance mapping") from exc
    db.refresh(row)
    return _attendance_mapping_response(db, row)


@attendance_mapping_router.patch("/{mapping_id}", response_model=AttendanceClassMappingResponse, dependencies=[EDIT_ACCESS])
def update_attendance_class_mapping(
    mapping_id: int, payload: AttendanceClassMappingUpdate, db: DbSession, claims: Claims
) -> AttendanceClassMappingResponse:
    row = db.get(AttendanceClassMapping, mapping_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Attendance class mapping not found")
    values = payload.model_dump(exclude={"expected_version"}, exclude_unset=True)
    if "instructional_class_id" in values:
        _active_class(db, values["instructional_class_id"])
        if db.scalar(
            select(AttendanceClassMapping.id).where(
                AttendanceClassMapping.instructional_class_id == values["instructional_class_id"],
                AttendanceClassMapping.is_active.is_(True),
                AttendanceClassMapping.id != mapping_id,
            )
        ):
            raise HTTPException(status_code=409, detail="Instructional class already has an attendance mapping")
    values = {key: value for key, value in values.items() if value != getattr(row, key)}
    if not values:
        raise HTTPException(status_code=422, detail="Mapping update contains no change")
    old_version = row.version
    try:
        changed = db.execute(
            update(AttendanceClassMapping)
            .where(AttendanceClassMapping.id == mapping_id, AttendanceClassMapping.version == payload.expected_version)
            .values(**values, version=AttendanceClassMapping.version + 1)
            .execution_options(synchronize_session=False)
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Instructional class already has an attendance mapping") from exc
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Attendance class mapping changed; reload it before saving")
    record_event(
        db,
        int(claims["sub"]),
        "attendance.class_mapping.updated",
        "attendance_class_mapping",
        str(mapping_id),
        {"fields": sorted(values), "previous_version": old_version, "version": old_version + 1},
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Instructional class already has an attendance mapping") from exc
    db.expire_all()
    updated = db.get(AttendanceClassMapping, mapping_id)
    return _attendance_mapping_response(db, updated)
