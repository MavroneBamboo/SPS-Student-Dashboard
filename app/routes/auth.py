import json
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Path, Response, status
from sqlalchemy import func, select

from app.audit import record_event
from app.config import get_settings
from app.deps import CurrentClaims, DbSession
from app.identity import current_actor, lock_identity
from app.models import AuditEvent, User
from app.schemas import LoginRequest, PasswordChangeRequest, TokenResponse
from app.security import create_access_token, decode_access_token, hash_password, verify_password

router = APIRouter(prefix="/auth", tags=["authentication"])

# A well-formed PBKDF2 value ensures unknown usernames take the same password
# verification path as known accounts without generating a new hash per request.
_DUMMY_PASSWORD_HASH = f"pbkdf2_sha256$310000${'00' * 16}${'00' * 32}"


def issue_session(db: DbSession, user: User) -> tuple[str, int]:
    settings = get_settings()
    session_id = secrets.token_hex(16)
    access_token = create_access_token(
        user.id,
        user.username,
        user.role,
        user.must_change_password,
        user.token_version,
        session_id=session_id,
    )
    expires_at = datetime.fromtimestamp(decode_access_token(access_token)["exp"], UTC)
    record_event(
        db,
        user.id,
        "auth.session.created",
        "auth_session",
        session_id,
        {"expires_at": expires_at.isoformat(), "token_version": user.token_version},
    )
    return access_token, settings.access_token_minutes * 60


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
    access_token, expires_in = issue_session(db, user)
    record_event(db, user.id, "auth.login.succeeded", "user", str(user.id), {"outcome": "success"})
    db.commit()
    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
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
    access_token, expires_in = issue_session(db, user)
    record_event(db, user.id, "auth.password.changed", "user", str(user.id))
    db.commit()
    return TokenResponse(
        access_token=access_token,
        expires_in=expires_in,
        role=user.role,
        must_change_password=False,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(db: DbSession, claims: CurrentClaims) -> None:
    revoke_session(db, claims, claims["jti"])


def _session_events(db: DbSession, user_id: int) -> list[AuditEvent]:
    return list(
        db.scalars(
            select(AuditEvent)
            .where(
                AuditEvent.actor_id == user_id,
                AuditEvent.entity_type == "auth_session",
                AuditEvent.action.in_(("auth.session.created", "auth.session.revoked")),
            )
            .order_by(AuditEvent.id)
        )
    )


def _session_states(events: list[AuditEvent]) -> dict[str, dict]:
    sessions = {}
    for event in events:
        if event.action == "auth.session.created":
            details = json.loads(event.details_json or "{}")
            sessions[event.entity_id] = {
                "id": event.entity_id,
                "created_at": event.created_at,
                "expires_at": datetime.fromisoformat(details["expires_at"]),
                "token_version": details["token_version"],
                "revoked": False,
            }
        elif event.entity_id in sessions:
            sessions[event.entity_id]["revoked"] = True
    return sessions


@router.get("/sessions")
def list_sessions(db: DbSession, claims: CurrentClaims) -> list[dict]:
    now = datetime.now(UTC)
    sessions = _session_states(_session_events(db, int(claims["sub"])))
    active = []
    for session in sessions.values():
        expires_at = session["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if session["revoked"] or session["token_version"] != claims["ver"] or expires_at <= now:
            continue
        created_at = session["created_at"]
        active.append(
            {
                "id": session["id"],
                "created_at": created_at.isoformat() if created_at else None,
                "expires_at": expires_at.isoformat(),
                "is_current": session["id"] == claims["jti"],
            }
        )
    return sorted(active, key=lambda session: session["created_at"] or "", reverse=True)


def revoke_session(db: DbSession, claims: dict, session_id: str) -> None:
    lock_identity(db)
    user = current_actor(db, claims)
    user_id = user.id
    session = db.scalar(
        select(AuditEvent.id).where(
            AuditEvent.actor_id == user_id,
            AuditEvent.action == "auth.session.created",
            AuditEvent.entity_type == "auth_session",
            AuditEvent.entity_id == session_id,
        )
    )
    if session is None and session_id != claims["jti"]:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    already_revoked = db.scalar(
        select(AuditEvent.id).where(
            AuditEvent.actor_id == user_id,
            AuditEvent.action == "auth.session.revoked",
            AuditEvent.entity_type == "auth_session",
            AuditEvent.entity_id == session_id,
        )
    )
    if already_revoked is None:
        record_event(db, user_id, "auth.session.revoked", "auth_session", session_id, {"outcome": "revoked"})
        db.commit()


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_user_session(
    db: DbSession,
    claims: CurrentClaims,
    session_id: str = Path(pattern=r"^[0-9a-f]{32}$"),
) -> Response:
    revoke_session(db, claims, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/sessions/revoke-others", status_code=status.HTTP_204_NO_CONTENT)
def revoke_other_sessions(db: DbSession, claims: CurrentClaims) -> None:
    lock_identity(db)
    user = current_actor(db, claims)
    user_id = user.id
    sessions = _session_states(_session_events(db, user_id))
    for session_id, session in sessions.items():
        expires_at = session["expires_at"]
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if (
            session_id == claims["jti"]
            or session["revoked"]
            or session["token_version"] != claims["ver"]
            or expires_at <= datetime.now(UTC)
        ):
            continue
        record_event(db, user_id, "auth.session.revoked", "auth_session", session_id, {"outcome": "revoked"})
    db.commit()
