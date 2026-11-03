from fastapi import APIRouter

from app.config import get_settings
from app.db import check_database

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
def live() -> dict:
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict:
    check_database()
    return {"status": "ready", "database": "ok", "revision": get_settings().app_build_sha}
