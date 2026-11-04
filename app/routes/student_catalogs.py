from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.deps import Claims, DbSession, require_roles
from app.models import Student, StudentReferenceValue
from app.reference_catalogs import normalized_reference_name
from app.schemas import StudentReferenceValueCreate, StudentReferenceValueResponse, StudentReferenceValueUpdate

router = APIRouter(prefix="/student-reference/catalogs", tags=["student reference catalogs"])
READ_ACCESS = Depends(require_roles("Superuser", "IT Administrator", "Operator", "Executive"))
EDIT_ACCESS = Depends(require_roles("Superuser", "IT Administrator"))
CATALOG_TYPES = {
    "categories": "CATEGORY",
    "institutions": "INSTITUTION",
    "academic-years": "ACADEMIC_YEAR",
}


def _catalog_type(catalog_name: str) -> str:
    catalog_type = CATALOG_TYPES.get(catalog_name)
    if catalog_type is None:
        raise HTTPException(status_code=404, detail="Reference catalog not found")
    return catalog_type


def _normalized(value: str) -> tuple[str, str]:
    name, key = normalized_reference_name(value)
    if not name or len(key) > 120:
        raise HTTPException(status_code=422, detail="Catalog name is invalid after normalization")
    return name, key


def _response(row: StudentReferenceValue) -> StudentReferenceValueResponse:
    return StudentReferenceValueResponse.model_validate(row, from_attributes=True)


def _validate_student_field_length(catalog_type: str, name: str) -> None:
    maximum = {"CATEGORY": 40, "ACADEMIC_YEAR": 20}.get(catalog_type, 120)
    if len(name) > maximum:
        field = catalog_type.lower().replace("_", " ")
        raise HTTPException(status_code=422, detail=f"{field} values cannot exceed {maximum} characters")


@router.get("/{catalog_name}", response_model=list[StudentReferenceValueResponse], dependencies=[READ_ACCESS])
def list_catalog(
    catalog_name: str,
    db: DbSession,
    claims: Claims,
    include_inactive: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
) -> list[StudentReferenceValueResponse]:
    catalog_type = _catalog_type(catalog_name)
    query = select(StudentReferenceValue).where(StudentReferenceValue.catalog_type == catalog_type)
    if not include_inactive:
        query = query.where(StudentReferenceValue.is_active.is_(True))
    rows = db.scalars(query.order_by(StudentReferenceValue.normalized_key, StudentReferenceValue.id).offset(offset).limit(limit)).all()
    return [_response(row) for row in rows]


@router.post(
    "/{catalog_name}",
    response_model=StudentReferenceValueResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[EDIT_ACCESS],
)
def create_catalog_value(
    catalog_name: str, payload: StudentReferenceValueCreate, db: DbSession, claims: Claims
) -> StudentReferenceValueResponse:
    catalog_type = _catalog_type(catalog_name)
    if catalog_type != "ACADEMIC_YEAR" and (payload.effective_from is not None or payload.effective_to is not None):
        raise HTTPException(status_code=422, detail="Effective dates are only supported for academic years")
    name, key = _normalized(payload.name)
    _validate_student_field_length(catalog_type, name)
    if (
        db.scalar(
            select(StudentReferenceValue.id).where(
                StudentReferenceValue.catalog_type == catalog_type, StudentReferenceValue.normalized_key == key
            )
        )
        is not None
    ):
        raise HTTPException(status_code=409, detail="A value with this name already exists in the catalog")
    row = StudentReferenceValue(
        catalog_type=catalog_type,
        name=name,
        normalized_key=key,
        description=payload.description,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        created_by=int(claims["sub"]),
        updated_by=int(claims["sub"]),
    )
    db.add(row)
    try:
        db.flush()
        record_event(
            db,
            int(claims["sub"]),
            "student_reference.created",
            "student_reference_value",
            str(row.id),
            {"catalog_type": catalog_type, "name": name},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A value with this name already exists in the catalog") from exc
    db.refresh(row)
    return _response(row)


@router.patch("/{catalog_name}/{value_id}", response_model=StudentReferenceValueResponse, dependencies=[EDIT_ACCESS])
def update_catalog_value(
    catalog_name: str,
    value_id: int,
    payload: StudentReferenceValueUpdate,
    db: DbSession,
    claims: Claims,
) -> StudentReferenceValueResponse:
    catalog_type = _catalog_type(catalog_name)
    row = db.scalar(
        select(StudentReferenceValue).where(StudentReferenceValue.id == value_id, StudentReferenceValue.catalog_type == catalog_type)
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Reference value not found")
    changes = payload.model_dump(exclude={"expected_version"}, exclude_unset=True)
    if catalog_type != "ACADEMIC_YEAR" and ("effective_from" in changes or "effective_to" in changes):
        raise HTTPException(status_code=422, detail="Effective dates are only supported for academic years")
    if "name" in changes:
        changes["name"], changes["normalized_key"] = _normalized(changes["name"])
        _validate_student_field_length(catalog_type, changes["name"])
        if changes["normalized_key"] != row.normalized_key:
            student_field = {"CATEGORY": "category", "ACADEMIC_YEAR": "academic_year", "INSTITUTION": "institution"}[catalog_type]
            student_column = getattr(Student, student_field)
            existing_values = db.scalars(select(student_column).where(student_column.is_not(None)).distinct()).all()
            if any(normalized_reference_name(value)[1] == row.normalized_key for value in existing_values):
                raise HTTPException(
                    status_code=409,
                    detail="A catalog value used by student profiles cannot be renamed; add the replacement and update profiles first",
                )
    changes = {key: value for key, value in changes.items() if value != getattr(row, key)}
    if not changes:
        raise HTTPException(status_code=422, detail="Catalog update contains no change")
    previous_version = row.version
    changes["version"] = StudentReferenceValue.version + 1
    changes["updated_by"] = int(claims["sub"])
    changed = db.execute(
        update(StudentReferenceValue)
        .where(
            StudentReferenceValue.id == value_id,
            StudentReferenceValue.catalog_type == catalog_type,
            StudentReferenceValue.version == payload.expected_version,
        )
        .values(**changes)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Reference value changed; reload it before saving")
    record_event(
        db,
        int(claims["sub"]),
        "student_reference.updated",
        "student_reference_value",
        str(value_id),
        {
            "catalog_type": catalog_type,
            "fields": sorted(key for key in changes if key not in {"version", "updated_by"}),
            "previous_version": previous_version,
            "version": previous_version + 1,
        },
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A value with this name already exists in the catalog") from exc
    db.expire_all()
    return _response(db.get(StudentReferenceValue, value_id))
