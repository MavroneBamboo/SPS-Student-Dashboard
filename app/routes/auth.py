from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.audit import record_event
from app.config import get_settings
from app.deps import CurrentClaims, DbSession
from app.models import User
from app.schemas import LoginRequest, PasswordChangeRequest, TokenResponse
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == payload.username, User.is_active.is_(True)))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user.id, user.username, user.role, user.must_change_password),
        expires_in=settings.access_token_minutes * 60,
        role=user.role,
        must_change_password=user.must_change_password,
    )


@router.post("/change-password", response_model=TokenResponse)
def change_password(payload: PasswordChangeRequest, db: DbSession, claims: CurrentClaims) -> TokenResponse:
    user = db.get(User, int(claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is unavailable")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")
    if verify_password(payload.new_password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="New password must differ from current password")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    record_event(db, user.id, "auth.password.changed", "user", str(user.id))
    db.commit()
    settings = get_settings()
    return TokenResponse(
        access_token=create_access_token(user.id, user.username, user.role),
        expires_in=settings.access_token_minutes * 60,
        role=user.role,
        must_change_password=False,
    )
