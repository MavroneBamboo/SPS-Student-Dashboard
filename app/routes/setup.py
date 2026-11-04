from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.config import get_settings
from app.deps import CurrentClaims, DbSession
from app.identity import current_actor, lock_identity
from app.models import SetupState, User
from app.schemas import InitialSetupComplete, InitialSetupResponse, UserResponse
from app.security import hash_password

router = APIRouter(prefix="/setup", tags=["initial setup"])


@router.get("/status")
def setup_status(db: DbSession, claims: CurrentClaims) -> dict[str, bool]:
    setup = db.get(SetupState, 1)
    if setup is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Setup state is unavailable")
    settings = get_settings()
    can_complete = (
        claims["role"] == "Superuser"
        and claims["username"].casefold() == settings.bootstrap_username.strip().casefold()
        and not claims["must_change_password"]
    )
    return {"required": not setup.completed, "can_complete": can_complete}


@router.post("/complete", response_model=InitialSetupResponse)
def complete_initial_setup(payload: InitialSetupComplete, db: DbSession, claims: CurrentClaims) -> InitialSetupResponse:
    lock_identity(db)
    actor = current_actor(db, claims)
    settings = get_settings()
    if actor.role != "Superuser" or actor.username.casefold() != settings.bootstrap_username.strip().casefold():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only the bootstrap Superuser can complete initial setup")
    if actor.must_change_password:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Change the bootstrap password before completing setup")

    setup = db.scalar(select(SetupState).where(SetupState.id == 1).with_for_update())
    if setup is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Setup state is unavailable")
    if setup.completed:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Initial setup is already complete")
    active_admin = db.scalar(select(User.id).where(User.role == "IT Administrator", User.is_active.is_(True)).limit(1).with_for_update())
    if active_admin is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="An active IT Administrator already exists")

    username = payload.username.strip()
    if username.casefold() == settings.bootstrap_username.strip().casefold():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Choose a named IT Administrator account")
    if db.scalar(select(User.id).where(func.lower(User.username) == username.casefold())) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    administrator = User(
        username=username,
        password_hash=hash_password(payload.temporary_password),
        role="IT Administrator",
        must_change_password=True,
        is_active=True,
    )
    db.add(administrator)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists") from exc

    setup.completed = True
    setup.completed_at = datetime.now(UTC)
    setup.completed_by = actor.id
    record_event(db, actor.id, "setup.initial_it_administrator.created", "user", str(administrator.id), {"username": username})
    record_event(db, actor.id, "setup.completed", "setup_state", "1", {"administrator_id": administrator.id})
    db.commit()
    db.refresh(administrator)
    return InitialSetupResponse(
        completed=True,
        administrator=UserResponse(
            id=administrator.id,
            username=administrator.username,
            role=administrator.role,
            is_active=administrator.is_active,
            must_change_password=administrator.must_change_password,
        ),
    )
