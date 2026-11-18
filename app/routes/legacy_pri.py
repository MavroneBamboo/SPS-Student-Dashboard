from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.audit import record_event
from app.config import get_settings
from app.deps import Claims, DbSession, require_roles
from app.legacy_pri import LegacyPriData, LegacyPriError, read_legacy_pri_bytes, reconcile_legacy_pri

router = APIRouter(
    prefix="/timetable/legacy-projects",
    tags=["legacy timetable reconciliation"],
    dependencies=[Depends(require_roles("Superuser", "IT Administrator"))],
)
MAX_LEGACY_PROJECT_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_INSPECT_ROWS = 5000


async def _read_project(request: Request) -> tuple[LegacyPriData, dict]:
    """Read and parse one bounded archive without retaining upload bytes."""
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/octet-stream":
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Upload a .pri project as application/octet-stream")
    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdigit() and int(declared_length) > MAX_LEGACY_PROJECT_UPLOAD_BYTES:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Legacy project exceeds the upload limit")

    archive_bytes = bytearray()
    async for chunk in request.stream():
        if len(archive_bytes) + len(chunk) > MAX_LEGACY_PROJECT_UPLOAD_BYTES:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Legacy project exceeds the upload limit")
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

    return data, reconcile_legacy_pri(data)


def _record_preflight(db, claims: Claims, action: str, report: dict) -> None:
    record_event(
        db,
        int(claims["sub"]),
        action,
        "legacy_timetable_project",
        "inspection" if action.endswith("inspected") else "preflight",
        {
            "valid": report["valid"],
            "counts": report["counts"],
            "issue_counts": report["issue_counts"],
        },
    )
    db.commit()


@router.post("/validate")
async def validate_legacy_project(request: Request, db: DbSession, claims: Claims) -> dict:
    """Run a redacted, read-only preflight on one bounded `.pri` archive."""
    _, report = await _read_project(request)
    _record_preflight(db, claims, "timetable.legacy_project.validated", report)
    return report


def _source_rows(rows: list[dict], *, kind: str) -> list[dict]:
    if len(rows) > MAX_INSPECT_ROWS:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Legacy project has too many rows to inspect")
    output = []
    for source_index, row in enumerate(rows):
        name = row.get("Name")
        full_name = row.get("FullName") if kind == "teacher" else None
        availability = row.get("Availability") if kind == "teacher" else None
        availability_flags = availability.split(":") if isinstance(availability, str) else []
        availability_profile = (
            "20-slot profile"
            if len(availability_flags) == 20 and all(flag in {"0", "1"} for flag in availability_flags)
            else "25-slot profile; mapping required"
            if len(availability_flags) == 25 and all(flag in {"0", "1"} for flag in availability_flags)
            else "Invalid or missing profile"
        )
        output.append(
            {
                "source_index": source_index,
                "source_id": row.get("Id") if type(row.get("Id")) is int else None,
                "name": name if isinstance(name, str) else None,
                "full_name": full_name if isinstance(full_name, str) else None,
                "is_adjunct": str(row.get("Adjunct", "")).strip().upper() == "Y" if kind == "teacher" else None,
                "availability_profile": availability_profile if kind == "teacher" else None,
            }
        )
    return output


@router.post("/inspect")
async def inspect_legacy_project(request: Request, db: DbSession, claims: Claims) -> dict:
    """Show source labels to IT/Superuser for explicit resource reconciliation."""
    data, report = await _read_project(request)
    if any(len(rows) > MAX_INSPECT_ROWS for rows in (data.teachers, data.subjects, data.classes, data.lessons)):
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Legacy project has too many rows to inspect")
    _record_preflight(db, claims, "timetable.legacy_project.inspected", report)
    return {
        "counts": report["counts"],
        "resources": {
            "teachers": _source_rows(data.teachers, kind="teacher"),
            "subjects": _source_rows(data.subjects, kind="subject"),
            "classes": _source_rows(data.classes, kind="class"),
        },
        "lesson_requirements": [
            {
                "source_index": index,
                "teacher": row.get("Teacher") if isinstance(row.get("Teacher"), str) else None,
                "subject": row.get("Subject") if isinstance(row.get("Subject"), str) else None,
                "class": row.get("InstClass") if isinstance(row.get("InstClass"), str) else None,
                "weekly_count": row.get("Count") if type(row.get("Count")) is int else None,
                "block_length": row.get("Length") if type(row.get("Length")) is int else None,
            }
            for index, row in enumerate(data.lessons)
        ],
    }
