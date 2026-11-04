from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select

from app.audit import record_event
from app.config import get_settings
from app.deps import CurrentClaims, DbSession
from app.identity import current_actor, lock_identity
from app.models import User
from app.schemas import LoginRequest, PasswordChangeRequest, TokenResponse
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])

# A well-formed PBKDF2 value ensures unknown usernames take the same password
# verification path as known accounts without generating a new hash per request.
_DUMMY_PASSWORD_HASH = f"pbkdf2_sha256$310000${'00' * 16}${'00' * 32}"


@router.get("/me")
def current_identity(claims: CurrentClaims) -> dict:
    return {key: claims[key] for key in ("sub", "username", "role", "must_change_password")}


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    username = payload.username.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.username) == username))
    password_valid = verify_password(payload.password, user.password_hash if user is not None else _DUMMY_PASSWORD_HASH)
    if user is None or not user.is_active or not password_valid:
        record_event(
            db,
            user.id if user is not None else 0,
            "auth.login.failed",
            "user" if user is not None else "authentication_attempt",
            str(user.id) if user is not None else "unknown",
            {"outcome": "failed"},
        )
        db.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    record_event(db, user.id, "auth.login.succeeded", "user", str(user.id), {"outcome": "success"})
    db.commit()
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user.id, user.username, user.role, user.must_change_password, user.token_version),
        expires_in=settings.access_token_minutes * 60,
        role=user.role,
        must_change_password=user.must_change_password,
    )


@router.post("/change-password", response_model=TokenResponse)
def change_password(payload: PasswordChangeRequest, db: DbSession, claims: CurrentClaims) -> TokenResponse:
    lock_identity(db)
    user = current_actor(db, claims)
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="New password must differ from current password")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.token_version += 1
    record_event(db, user.id, "auth.password.changed", "user", str(user.id))
    db.commit()
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user.id, user.username, user.role, token_version=user.token_version),
        expires_in=settings.access_token_minutes * 60,
        role=user.role,
        must_change_password=False,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(db: DbSession, claims: CurrentClaims) -> None:
    lock_identity(db)
    user = current_actor(db, claims)
    user.token_version += 1
    record_event(db, user.id, "auth.logout", "user", str(user.id))
    db.commit()
