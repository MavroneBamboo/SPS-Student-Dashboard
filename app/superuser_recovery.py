from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import record_event
from app.identity import lock_identity
from app.models import User
from app.security import hash_password


class RecoveryRefused(ValueError):
    """The requested privileged recovery does not meet its safety checks."""


def recover_superuser(db: Session, username: str, performed_by: str, reason: str, new_password: str) -> int:
    normalized_username = username.strip()
    operator = performed_by.strip()
    recovery_reason = reason.strip()
    if not normalized_username or len(normalized_username) > 120:
        raise RecoveryRefused("A valid existing Superuser username is required.")
    if not operator or len(operator) > 120:
        raise RecoveryRefused("An IT operator identity is required.")
    if not recovery_reason or len(recovery_reason) > 500:
        raise RecoveryRefused("A recovery reason of 1 to 500 characters is required.")
    if not 12 <= len(new_password) <= 200:
        raise RecoveryRefused("The recovery password must be between 12 and 200 characters.")

    lock_identity(db)
    target = db.scalar(
        select(User)
        .where(func.lower(User.username) == normalized_username.lower())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if target is None or target.role != "Superuser":
        raise RecoveryRefused("Recovery is limited to an existing Superuser account.")

    other_active_superuser = db.scalar(
        select(User.id).where(User.role == "Superuser", User.is_active.is_(True), User.id != target.id).with_for_update()
    )
    if other_active_superuser is not None:
        raise RecoveryRefused("Another active Superuser exists; use regular account administration instead.")

    target.password_hash = hash_password(new_password)
    target.must_change_password = True
    target.is_active = True
    target.token_version += 1
    record_event(
        db,
        0,
        "security.superuser.recovered",
        "user",
        str(target.id),
        {"performed_by": operator, "reason": recovery_reason},
    )
    db.commit()
    return target.id
