from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.deps import Claims, DbSession, require_roles
from app.lesson_validation import validate_lesson_resources
from app.models import LessonRequirement
from app.schemas import LessonRequirementCreate, LessonRequirementResponse, LessonRequirementUpdate
from app.timetable_lock import lock_timetable_configuration

router = APIRouter(
    prefix="/timetable/lessons",
    tags=["lesson requirements"],
    dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator"))],
)


def _response(row: LessonRequirement) -> LessonRequirementResponse:
    return LessonRequirementResponse.model_validate(row, from_attributes=True)


def _get(db: DbSession, lesson_id: int) -> LessonRequirement:
    row = db.get(LessonRequirement, lesson_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Lesson requirement not found")
    return row


@router.get("", response_model=list[LessonRequirementResponse])
def list_lessons(
    db: DbSession,
    claims: Claims,
    academic_year: str | None = Query(default=None, min_length=1, max_length=20),
    instructional_class_id: int | None = Query(default=None, gt=0),
    include_inactive: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[LessonRequirementResponse]:
    query = select(LessonRequirement)
    if academic_year is not None:
        query = query.where(LessonRequirement.academic_year == academic_year.strip().upper())
    if instructional_class_id is not None:
        query = query.where(LessonRequirement.instructional_class_id == instructional_class_id)
    if not include_inactive:
        query = query.where(LessonRequirement.is_active.is_(True))
    return [_response(row) for row in db.scalars(query.order_by(LessonRequirement.id).offset(offset).limit(limit)).all()]


@router.get("/{lesson_id}", response_model=LessonRequirementResponse)
def get_lesson(lesson_id: int, db: DbSession, claims: Claims) -> LessonRequirementResponse:
    return _response(_get(db, lesson_id))


@router.post("", response_model=LessonRequirementResponse, status_code=status.HTTP_201_CREATED)
def create_lesson(payload: LessonRequirementCreate, db: DbSession, claims: Claims) -> LessonRequirementResponse:
    lock_timetable_configuration(db)
    validate_lesson_resources(db, payload)
    actor_id = int(claims["sub"])
    row = LessonRequirement(**payload.model_dump(), is_active=True, version=1, created_by=actor_id, updated_by=actor_id)
    try:
        db.add(row)
        db.flush()
        record_event(db, actor_id, "timetable.lesson.created", "lesson_requirement", str(row.id), payload.model_dump())
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Lesson requirement already exists; edit or restore the existing requirement") from exc
    db.refresh(row)
    return _response(row)


@router.put("/{lesson_id}", response_model=LessonRequirementResponse)
def update_lesson(lesson_id: int, payload: LessonRequirementUpdate, db: DbSession, claims: Claims) -> LessonRequirementResponse:
    lock_timetable_configuration(db)
    row = _get(db, lesson_id)
    validate_lesson_resources(db, payload, is_active=payload.is_active)
    previous = _response(row).model_dump()
    changes = payload.model_dump(exclude={"expected_version"})
    actor_id = int(claims["sub"])
    try:
        changed = db.execute(
            update(LessonRequirement)
            .where(LessonRequirement.id == lesson_id, LessonRequirement.version == payload.expected_version)
            .values(**changes, version=LessonRequirement.version + 1, updated_by=actor_id)
        )
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Lesson changed since it was loaded; reload before saving")
        record_event(db, actor_id, "timetable.lesson.updated", "lesson_requirement", str(lesson_id), {"before": previous, "after": changes})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Lesson requirement conflicts with an existing requirement") from exc
    db.refresh(row)
    return _response(row)


@router.delete("/{lesson_id}", response_model=LessonRequirementResponse)
def archive_lesson(lesson_id: int, db: DbSession, claims: Claims, expected_version: int = Query(ge=1)) -> LessonRequirementResponse:
    lock_timetable_configuration(db)
    row = _get(db, lesson_id)
    actor_id = int(claims["sub"])
    changed = db.execute(
        update(LessonRequirement)
        .where(LessonRequirement.id == lesson_id, LessonRequirement.version == expected_version, LessonRequirement.is_active.is_(True))
        .values(is_active=False, version=LessonRequirement.version + 1, updated_by=actor_id)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Lesson changed or is already archived; reload before saving")
    record_event(db, actor_id, "timetable.lesson.archived", "lesson_requirement", str(lesson_id), {"previous_version": expected_version})
    db.commit()
    db.refresh(row)
    return _response(row)
