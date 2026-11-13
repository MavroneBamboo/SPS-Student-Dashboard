from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.audit import record_event
from app.config import get_settings
from app.deps import Claims, DbSession, require_roles
from app.legacy_pri import LegacyPriError, read_legacy_pri_bytes, reconcile_legacy_pri

router = APIRouter(
    prefix="/timetable/legacy-projects",
    tags=["legacy timetable reconciliation"],
    dependencies=[Depends(require_roles("Superuser", "IT Administrator"))],
)
MAX_LEGACY_PROJECT_UPLOAD_BYTES = 10 * 1024 * 1024


@router.post("/validate")
async def validate_legacy_project(request: Request, db: DbSession, claims: Claims) -> dict:
    """Run a redacted, read-only preflight on one bounded `.pri` archive."""
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/octet-stream":
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Upload a .pri project as application/octet-stream")
    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdigit() and int(declared_length) > MAX_LEGACY_PROJECT_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Legacy project exceeds the upload limit")

    archive_bytes = bytearray()
    async for chunk in request.stream():
        if len(archive_bytes) + len(chunk) > MAX_LEGACY_PROJECT_UPLOAD_BYTES:
            raise HTTPException(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Legacy project exceeds the upload limit")
        archive_bytes.extend(chunk)
    if not archive_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Legacy project is empty")

    key_hex = get_settings().legacy_pri_key_hex.strip()
    if not key_hex:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Legacy project validation is not configured")
    try:
        key = bytes.fromhex(key_hex)
        data = read_legacy_pri_bytes(bytes(archive_bytes), key)
    except (ValueError, LegacyPriError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Legacy project could not be validated") from exc
    finally:
        archive_bytes.clear()

    report = reconcile_legacy_pri(data)
    record_event(
        db,
        int(claims["sub"]),
        "timetable.legacy_project.validated",
        "legacy_timetable_project",
        "preflight",
        {
            "valid": report["valid"],
            "counts": report["counts"],
            "issue_counts": report["issue_counts"],
        },
    )
    db.commit()
    return report
