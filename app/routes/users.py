from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.audit import record_event
from app.deps import Claims, DbSession, require_roles
from app.models import User
from app.schemas import UserCreate, UserResponse, UserUpdate
from app.security import hash_password

router = APIRouter(prefix="/users", tags=["user administration"])
SUPERUSER_ONLY = Depends(require_roles("Superuser"))


def user_response(row: User) -> UserResponse:
    return UserResponse(
        id=row.id, username=row.username, role=row.role, is_active=row.is_active, must_change_password=row.must_change_password
    )


@router.get("", response_model=list[UserResponse], dependencies=[SUPERUSER_ONLY])
def list_users(db: DbSession, claims: Claims) -> list[UserResponse]:
    return [user_response(row) for row in db.scalars(select(User).order_by(User.username)).all()]


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED, dependencies=[SUPERUSER_ONLY])
def create_user(payload: UserCreate, db: DbSession, claims: Claims) -> UserResponse:
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
    db.flush()
    record_event(db, int(claims["sub"]), "user.created", "user", str(row.id), {"username": row.username, "role": row.role})
    db.commit()
    db.refresh(row)
    return user_response(row)


@router.patch("/{user_id}", response_model=UserResponse, dependencies=[SUPERUSER_ONLY])
def update_user(user_id: int, payload: UserUpdate, db: DbSession, claims: Claims) -> UserResponse:
    row = db.get(User, user_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    changes = payload.model_dump(exclude_unset=True)
    if row.id == int(claims["sub"]) and changes.get("is_active") is False:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="You cannot deactivate your own account")
    demotes_active_superuser = (
        row.role == "Superuser"
        and row.is_active
        and (changes.get("role", row.role) != "Superuser" or changes.get("is_active", row.is_active) is False)
    )
    if demotes_active_superuser:
        other_active_superusers = (
            db.scalar(select(func.count()).select_from(User).where(User.role == "Superuser", User.is_active.is_(True), User.id != row.id))
            or 0
        )
        if other_active_superusers == 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="At least one active Superuser must remain")
    previous = {"role": row.role, "is_active": row.is_active}
    for field, value in changes.items():
        setattr(row, field, value)
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
