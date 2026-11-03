from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuthSession, User
from app.security import decode_access_token

bearer = HTTPBearer(auto_error=False)
DbSession = Annotated[Session, Depends(get_db)]


def authenticated_claims(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)], db: DbSession) -> dict:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        token_claims = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token") from exc
    try:
        user_id = int(token_claims["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid access token") from exc
    user = db.get(User, user_id)
    if user is None or not user.is_active or token_claims["ver"] != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account is unavailable")
    session = db.scalar(select(AuthSession).where(AuthSession.jti == token_claims["jti"], AuthSession.user_id == user.id))
    if session is None or session.revoked_at is not None or session.token_version != user.token_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session is unavailable")
    return {
        **token_claims,
        "sub": str(user.id),
        "username": user.username,
        "role": user.role,
        "must_change_password": user.must_change_password,
    }


CurrentClaims = Annotated[dict, Depends(authenticated_claims)]


def current_claims(claims: CurrentClaims) -> dict:
    if claims["must_change_password"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Change your password before using the application")
    return claims


Claims = Annotated[dict, Depends(current_claims)]


def require_roles(*roles: str):
    def dependency(claims: Claims) -> dict:
        if claims.get("role") not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return claims

    return dependency
