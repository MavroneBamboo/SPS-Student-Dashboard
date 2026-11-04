"""Verify and rotate application-encrypted database values atomically."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.crypto import (
    decrypt_sensitive,
    decrypt_sensitive_bytes,
    encrypt_sensitive,
    encrypt_sensitive_bytes,
    is_current_encryption,
)
from app.models import AttendanceRosterEntry, Student, StudentImportBatch


def _rotate_text(value: str | None) -> tuple[str | None, bool]:
    if value is None:
        return None, False
    plaintext = decrypt_sensitive(value)
    if is_current_encryption(value):
        return value, False
    return encrypt_sensitive(plaintext), True


def _rotate_bytes(value: bytes | None) -> tuple[bytes | None, bool]:
    if value is None:
        return None, False
    plaintext = decrypt_sensitive_bytes(value)
    if is_current_encryption(value):
        return value, False
    return encrypt_sensitive_bytes(plaintext), True


def rotate_encrypted_data(db: Session, *, apply: bool) -> dict[str, int]:
    """Verify all protected values and, when requested, re-encrypt old-key values.

    The caller owns the transaction. Any unreadable value raises before the caller
    commits, so an apply run is all-or-nothing.
    """
    verified = 0
    to_rotate = 0
    by_table: dict[str, int] = {}

    text_tables = (
        ("students", Student, tuple(column.name for column in Student.__table__.columns if column.name.endswith("_encrypted"))),
        ("attendance_roster_entries", AttendanceRosterEntry, ("student_name_encrypted",)),
    )
    for table_name, model, fields in text_tables:
        query = select(model)
        if apply:
            query = query.with_for_update()
        rows = db.scalars(query.execution_options(yield_per=250))
        for row in rows:
            for field in fields:
                value = getattr(row, field)
                replacement, changed = _rotate_text(value)
                if value is not None:
                    verified += 1
                if changed:
                    to_rotate += 1
                    by_table[table_name] = by_table.get(table_name, 0) + 1
                    if apply:
                        setattr(row, field, replacement)

    query = select(StudentImportBatch)
    if apply:
        query = query.with_for_update()
    rows = db.scalars(query.execution_options(yield_per=100))
    for row in rows:
        for field in ("source_ciphertext", "rows_ciphertext"):
            value = getattr(row, field)
            replacement, changed = _rotate_bytes(value)
            if value is None:
                continue
            verified += 1
            if changed:
                to_rotate += 1
                by_table["student_import_batches"] = by_table.get("student_import_batches", 0) + 1
                if apply:
                    setattr(row, field, replacement)

    return {
        "encrypted_values_verified": verified,
        "values_to_rotate": to_rotate,
        **{f"{table}_values_to_rotate": count for table, count in sorted(by_table.items())},
    }
