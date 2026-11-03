from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.deps import Claims, DbSession, require_roles
from app.models import AcademicYear, Institution, StudentCategory
from app.schemas import (
    AcademicYearCreate,
    AcademicYearResponse,
    AcademicYearUpdate,
    InstitutionCreate,
    InstitutionResponse,
    InstitutionUpdate,
    StudentCategoryCreate,
    StudentCategoryResponse,
    StudentCategoryUpdate,
)
from app.student_catalogs import normalize_catalog_code

router = APIRouter(prefix="/student-reference", tags=["student reference catalogs"])
READ_ACCESS = Depends(require_roles("Operator", "IT Administrator", "Executive", "Superuser"))
EDIT_ACCESS = Depends(require_roles("IT Administrator", "Superuser"))


@router.get("/academic-years", response_model=list[AcademicYearResponse], dependencies=[READ_ACCESS])
def list_academic_years(db: DbSession) -> list[AcademicYearResponse]:
    rows = db.scalars(select(AcademicYear).order_by(AcademicYear.code_key)).all()
    return [AcademicYearResponse.model_validate(row, from_attributes=True) for row in rows]


@router.post("/academic-years", response_model=AcademicYearResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_academic_year(payload: AcademicYearCreate, db: DbSession, claims: Claims) -> AcademicYearResponse:
    code = " ".join(payload.code.strip().split()).upper()
    code_key = code.casefold()
    if not code or len(code) > 20:
        raise HTTPException(status_code=422, detail="Academic year code must contain 1 to 20 characters")
    if db.scalar(select(AcademicYear.id).where(AcademicYear.code_key == code_key)) is not None:
        raise HTTPException(status_code=409, detail="An academic year with this code already exists")
    row = AcademicYear(
        code=code,
        code_key=code_key,
        label=payload.label.strip(),
        starts_on=payload.starts_on,
        ends_on=payload.ends_on,
        is_active=payload.is_active,
        created_by=int(claims["sub"]),
    )
    db.add(row)
    try:
        db.flush()
        record_event(db, int(claims["sub"]), "student.academic_year.created", "academic_year", str(row.id), {"code": row.code})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An academic year with this code already exists") from exc
    db.refresh(row)
    return AcademicYearResponse.model_validate(row, from_attributes=True)


@router.patch("/academic-years/{academic_year_id}", response_model=AcademicYearResponse, dependencies=[EDIT_ACCESS])
def update_academic_year(academic_year_id: int, payload: AcademicYearUpdate, db: DbSession, claims: Claims) -> AcademicYearResponse:
    row = db.get(AcademicYear, academic_year_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Academic year not found")
    values = payload.model_dump(exclude={"expected_version"}, exclude_unset=True)
    if not values or all(getattr(row, key) == value for key, value in values.items()):
        raise HTTPException(status_code=422, detail="Academic year update contains no change")
    starts_on = values.get("starts_on", row.starts_on)
    ends_on = values.get("ends_on", row.ends_on)
    active = values.get("is_active", row.is_active)
    if starts_on is None or ends_on is None:
        if active:
            raise HTTPException(status_code=422, detail="Set both academic year dates before activating it")
        if (starts_on is None) != (ends_on is None):
            raise HTTPException(status_code=422, detail="Set or clear both academic year dates together")
    if starts_on and ends_on and ends_on < starts_on:
        raise HTTPException(status_code=422, detail="Academic year end date must be on or after its start date")
    previous_version = row.version
    changed = db.execute(
        update(AcademicYear)
        .where(AcademicYear.id == academic_year_id, AcademicYear.version == payload.expected_version)
        .values(**values, version=AcademicYear.version + 1)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Academic year changed; reload it before saving")
    record_event(
        db,
        int(claims["sub"]),
        "student.academic_year.updated",
        "academic_year",
        str(academic_year_id),
        {"fields": sorted(values), "previous_version": previous_version, "version": previous_version + 1},
    )
    db.commit()
    db.expire_all()
    return AcademicYearResponse.model_validate(db.get(AcademicYear, academic_year_id), from_attributes=True)


@router.get("/categories", response_model=list[StudentCategoryResponse], dependencies=[READ_ACCESS])
def list_student_categories(db: DbSession) -> list[StudentCategoryResponse]:
    rows = db.scalars(select(StudentCategory).order_by(StudentCategory.code_key)).all()
    return [StudentCategoryResponse.model_validate(row, from_attributes=True) for row in rows]


@router.post("/categories", response_model=StudentCategoryResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_student_category(payload: StudentCategoryCreate, db: DbSession, claims: Claims) -> StudentCategoryResponse:
    try:
        code, code_key = normalize_catalog_code(payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if db.scalar(select(StudentCategory.id).where(StudentCategory.code_key == code_key)) is not None:
        raise HTTPException(status_code=409, detail="A student category with this code already exists")
    row = StudentCategory(code=code, code_key=code_key, name=payload.name.strip(), created_by=int(claims["sub"]))
    db.add(row)
    try:
        db.flush()
        record_event(db, int(claims["sub"]), "student.category.created", "student_category", str(row.id), {"code": row.code})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A student category with this code already exists") from exc
    db.refresh(row)
    return StudentCategoryResponse.model_validate(row, from_attributes=True)


@router.patch("/categories/{category_id}", response_model=StudentCategoryResponse, dependencies=[EDIT_ACCESS])
def update_student_category(category_id: int, payload: StudentCategoryUpdate, db: DbSession, claims: Claims) -> StudentCategoryResponse:
    row = db.get(StudentCategory, category_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Student category not found")
    values = {
        key: value
        for key, value in payload.model_dump(exclude={"expected_version"}, exclude_unset=True).items()
        if value != getattr(row, key)
    }
    if not values:
        raise HTTPException(status_code=422, detail="Category update contains no change")
    previous_version = row.version
    changed = db.execute(
        update(StudentCategory)
        .where(StudentCategory.id == category_id, StudentCategory.version == payload.expected_version)
        .values(**values, version=StudentCategory.version + 1)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Student category changed; reload it before saving")
    record_event(
        db,
        int(claims["sub"]),
        "student.category.updated",
        "student_category",
        str(category_id),
        {"fields": sorted(values), "previous_version": previous_version, "version": previous_version + 1},
    )
    db.commit()
    db.expire_all()
    return StudentCategoryResponse.model_validate(db.get(StudentCategory, category_id), from_attributes=True)


@router.get("/institutions", response_model=list[InstitutionResponse], dependencies=[READ_ACCESS])
def list_institutions(db: DbSession) -> list[InstitutionResponse]:
    rows = db.scalars(select(Institution).order_by(Institution.code_key)).all()
    return [InstitutionResponse.model_validate(row, from_attributes=True) for row in rows]


@router.post("/institutions", response_model=InstitutionResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_institution(payload: InstitutionCreate, db: DbSession, claims: Claims) -> InstitutionResponse:
    try:
        code, code_key = normalize_catalog_code(payload.code)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if db.scalar(select(Institution.id).where(Institution.code_key == code_key)) is not None:
        raise HTTPException(status_code=409, detail="An institution with this code already exists")
    row = Institution(code=code, code_key=code_key, name=payload.name.strip(), created_by=int(claims["sub"]))
    db.add(row)
    try:
        db.flush()
        record_event(db, int(claims["sub"]), "student.institution.created", "institution", str(row.id), {"code": row.code})
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="An institution with this code already exists") from exc
    db.refresh(row)
    return InstitutionResponse.model_validate(row, from_attributes=True)


@router.patch("/institutions/{institution_id}", response_model=InstitutionResponse, dependencies=[EDIT_ACCESS])
def update_institution(institution_id: int, payload: InstitutionUpdate, db: DbSession, claims: Claims) -> InstitutionResponse:
    row = db.get(Institution, institution_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Institution not found")
    values = {
        key: value
        for key, value in payload.model_dump(exclude={"expected_version"}, exclude_unset=True).items()
        if value != getattr(row, key)
    }
    if not values:
        raise HTTPException(status_code=422, detail="Institution update contains no change")
    previous_version = row.version
    changed = db.execute(
        update(Institution)
        .where(Institution.id == institution_id, Institution.version == payload.expected_version)
        .values(**values, version=Institution.version + 1)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Institution changed; reload it before saving")
    record_event(
        db,
        int(claims["sub"]),
        "student.institution.updated",
        "institution",
        str(institution_id),
        {"fields": sorted(values), "previous_version": previous_version, "version": previous_version + 1},
    )
    db.commit()
    db.expire_all()
    return InstitutionResponse.model_validate(db.get(Institution, institution_id), from_attributes=True)
