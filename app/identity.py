"""Serialize security mutations and re-check the actor after acquiring the lock."""

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import User


def lock_identity(db: Session) -> None:
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:namespace, :resource)"), {"namespace": 5460051, "resource": 2})


def current_actor(db: Session, claims: dict) -> User:
    user = db.get(User, int(claims["sub"]), populate_existing=True)
    if user is None or not user.is_active or user.token_version != claims["ver"]:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is unavailable")
    return user
