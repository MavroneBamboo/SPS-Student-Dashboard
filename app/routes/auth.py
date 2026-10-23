from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import DbSession
from app.models import User
from app.schemas import LoginRequest, TokenResponse
from app.security import create_access_token, verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = db.scalar(select(User).where(User.username == payload.username, User.is_active.is_(True)))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    settings = get_settings()
    return TokenResponse(access_token=create_access_token(user.id, user.username, user.role), expires_in=settings.access_token_minutes * 60, role=user.role)
