from unicodedata import normalize

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StudentReferenceValue


def normalized_reference_name(value: str) -> tuple[str, str]:
    display_name = " ".join(value.split())
    normalized_key = " ".join(normalize("NFKC", display_name).split()).casefold()
    return display_name, normalized_key


def resolve_active_reference(db: Session, catalog_type: str, value: str) -> StudentReferenceValue | None:
    _, key = normalized_reference_name(value)
    if not key:
        return None
    return db.scalar(
        select(StudentReferenceValue)
        .where(
            StudentReferenceValue.catalog_type == catalog_type,
            StudentReferenceValue.normalized_key == key,
            StudentReferenceValue.is_active.is_(True),
        )
        .with_for_update()
    )
