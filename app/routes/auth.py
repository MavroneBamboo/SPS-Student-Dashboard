import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Path, status
from sqlalchemy import delete, func, select

from app.audit import record_event
from app.config import get_settings
from app.deps import CurrentClaims, DbSession
from app.identity import current_actor, lock_identity
from app.models import AuthSession, User
from app.schemas import AuthSessionResponse, LoginRequest, PasswordChangeRequest, TokenResponse
from app.security import create_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])


def _issue_session(db, user: User) -> TokenResponse:
    settings = get_settings()
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(minutes=settings.access_token_minutes)
    session_id = secrets.token_hex(16)
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= issued_at))
    db.add(
        AuthSession(
            jti=session_id,
            user_id=user.id,
            token_version=user.token_version,
            expires_at=expires_at,
        )
    )
    return TokenResponse(
        access_token=create_access_token(
            user.id,
            user.username,
            user.role,
            user.must_change_password,
            user.token_version,
            session_id=session_id,
            issued_at=issued_at,
        ),
        expires_in=settings.access_token_minutes * 60,
        role=user.role,
        must_change_password=user.must_change_password,
    )


@router.get("/me")
def current_identity(claims: CurrentClaims) -> dict:
    return {key: claims[key] for key in ("sub", "username", "role", "must_change_password")}


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = db.scalar(select(User).where(func.lower(User.username) == payload.username.strip().lower(), User.is_active.is_(True)))
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")
    token = _issue_session(db, user)
    db.commit()
    return token


@router.get("/sessions", response_model=list[AuthSessionResponse])
def list_sessions(db: DbSession, claims: CurrentClaims) -> list[AuthSessionResponse]:
    user = current_actor(db, claims)
    now = datetime.now(UTC)
    sessions = db.scalars(
        select(AuthSession)
        .where(
            AuthSession.user_id == user.id,
            AuthSession.token_version == user.token_version,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
        .order_by(AuthSession.created_at.desc(), AuthSession.jti)
    ).all()
    return [
        AuthSessionResponse(
            session_id=session.jti,
            created_at=session.created_at,
            expires_at=session.expires_at,
            is_current=session.jti == claims["jti"],
        )
        for session in sessions
    ]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_session(
    db: DbSession,
    claims: CurrentClaims,
    session_id: str = Path(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$"),
) -> None:
    user = current_actor(db, claims)
    session = db.scalar(select(AuthSession).where(AuthSession.jti == session_id, AuthSession.user_id == user.id).with_for_update())
    if session is None or session.revoked_at is not None or session.token_version != user.token_version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    session.revoked_at = datetime.now(UTC)
    record_event(db, user.id, "auth.session.revoked", "user", str(user.id))
    db.commit()


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
    token = _issue_session(db, user)
    record_event(db, user.id, "auth.password.changed", "user", str(user.id))
    db.commit()
    return token


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(db: DbSession, claims: CurrentClaims) -> None:
    lock_identity(db)
    user = current_actor(db, claims)
    session = db.scalar(select(AuthSession).where(AuthSession.jti == claims["jti"], AuthSession.user_id == user.id).with_for_update())
    if session is None or session.revoked_at is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is unavailable")
    session.revoked_at = datetime.now(UTC)
    record_event(db, user.id, "auth.logout", "user", str(user.id))
    db.commit()
