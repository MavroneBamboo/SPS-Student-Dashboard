from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.deps import Claims, DbSession, require_roles
from app.identity import current_actor, lock_identity
from app.models import User
from app.schemas import UserCreate, UserPasswordReset, UserResponse, UserUpdate
from app.security import hash_password

router = APIRouter(prefix="/users", tags=["user administration"])
ADMIN_ONLY = Depends(require_roles("Superuser", "IT Administrator"))


def ensure_target(actor: User, row: User, role: str | None = None) -> None:
    if actor.role not in ("Superuser", "IT Administrator"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    if actor.role == "IT Administrator" and (row.role == "Superuser" or role == "Superuser"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Superuser accounts require Superuser access")


def preserve_last_admin(db: DbSession, row: User, changes: dict) -> None:
    if (
        row.is_active
        and row.role in ("Superuser", "IT Administrator")
        and (changes.get("role", row.role) != row.role or changes.get("is_active", row.is_active) is False)
    ):
        others = (
            db.scalar(select(func.count()).select_from(User).where(User.role == row.role, User.is_active.is_(True), User.id != row.id)) or 0
        )
        if others == 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"At least one active {row.role} must remain")


def user_response(row: User) -> UserResponse:
    return UserResponse(
        id=row.id, username=row.username, role=row.role, is_active=row.is_active, must_change_password=row.must_change_password
    )


@router.get("", response_model=list[UserResponse], dependencies=[ADMIN_ONLY])
def list_users(db: DbSession, claims: Claims) -> list[UserResponse]:
    query = select(User).order_by(User.username)
    if claims["role"] == "IT Administrator":
        query = query.where(User.role != "Superuser")
    return [user_response(row) for row in db.scalars(query).all()]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED, dependencies=[ADMIN_ONLY])
def create_user(payload: UserCreate, db: DbSession, claims: Claims) -> UserResponse:
    lock_identity(db)
    actor = current_actor(db, claims)
    ensure_target(actor, actor, payload.role)
    username = payload.username.strip()
    if db.scalar(select(User).where(func.lower(User.username) == username.lower())) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")
    row = User(
        username=username,
        password_hash=hash_password(payload.temporary_password),
        role=payload.role,
        must_change_password=True,
        is_active=True,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists") from exc
    record_event(db, int(claims["sub"]), "user.created", "user", str(row.id), {"username": row.username, "role": row.role})
    db.commit()
    db.refresh(row)
    return user_response(row)


@router.patch("/{user_id}", response_model=UserResponse, dependencies=[ADMIN_ONLY])
def update_user(user_id: int, payload: UserUpdate, db: DbSession, claims: Claims) -> UserResponse:
    lock_identity(db)
    actor = current_actor(db, claims)
    row = db.get(User, user_id, populate_existing=True)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    changes = payload.model_dump(exclude_unset=True)
    ensure_target(actor, row, changes.get("role"))
    if row.id == int(claims["sub"]) and changes.get("is_active") is False:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="You cannot deactivate your own account")
    preserve_last_admin(db, row, changes)
    previous = {"role": row.role, "is_active": row.is_active}
    for field, value in changes.items():
        setattr(row, field, value)
    if any(previous[field] != getattr(row, field) for field in previous):
        row.token_version += 1
    record_event(
        db,
        int(claims["sub"]),
        "user.updated",
        "user",
        str(row.id),
        {"before": previous, "after": {"role": row.role, "is_active": row.is_active}},
    )
    db.commit()
    db.refresh(row)
    return user_response(row)


@router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT, dependencies=[ADMIN_ONLY])
def reset_password(user_id: int, payload: UserPasswordReset, db: DbSession, claims: Claims) -> None:
    lock_identity(db)
    actor = current_actor(db, claims)
    row = db.get(User, user_id, populate_existing=True)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    ensure_target(actor, row)
    if row.id == actor.id:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Use change-password for your own account")
    row.password_hash = hash_password(payload.temporary_password)
    row.must_change_password = True
    row.token_version += 1
    record_event(db, actor.id, "user.password.reset", "user", str(row.id))
    db.commit()
