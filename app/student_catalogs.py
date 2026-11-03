from fastapi import HTTPException
from sqlalchemy import select

from app.models import Institution, StudentCategory


def normalize_catalog_code(value: str) -> tuple[str, str]:
    code = " ".join(value.strip().split())
    if not code or len(code) > 40:
        raise ValueError("Catalog code must contain 1 to 40 characters")
    return code, code.casefold()


def active_student_category(db, value: str) -> StudentCategory:
    try:
        _, key = normalize_catalog_code(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    category = db.scalar(select(StudentCategory).where(StudentCategory.code_key == key).with_for_update())
    if category is None or not category.is_active:
        raise HTTPException(status_code=422, detail="Select an active student category")
    return category


def active_institution(db, institution_id: int | None) -> Institution | None:
    if institution_id is None:
        return None
    institution = db.scalar(select(Institution).where(Institution.id == institution_id).with_for_update())
    if institution is None or not institution.is_active:
        raise HTTPException(status_code=422, detail="Select an active institution")
    return institution
