import hashlib
import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.config import get_settings
from app.crypto import encrypt_sensitive_bytes
from app.deps import Claims, DbSession, require_roles
from app.legacy_pri import MAX_ARCHIVE_BYTES, LegacyPriError, read_legacy_pri, reconcile_legacy_pri
from app.models import LegacyTimetableImport

router = APIRouter(
    prefix="/timetable/legacy-imports",
    tags=["legacy timetable staging imports"],
    dependencies=[Depends(require_roles("Superuser", "IT Administrator"))],
)
UPLOAD_MEDIA_TYPE = "application/octet-stream"


class LegacyTimetableImportSummary(BaseModel):
    id: int
    source_sha256: str
    status: str
    counts: dict[str, int]
    issue_counts: dict[str, int]
    valid: bool
    import_ready: bool
    created_by: int
    created_at: datetime


class LegacyTimetableImportDetail(LegacyTimetableImportSummary):
    issues: list[dict[str, Any]]


def _report(row: LegacyTimetableImport) -> dict[str, Any]:
    try:
        return json.loads(row.report_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail="Stored legacy reconciliation report is invalid") from exc


def _summary(row: LegacyTimetableImport) -> LegacyTimetableImportSummary:
    report = _report(row)
    return LegacyTimetableImportSummary(
        id=row.id,
        source_sha256=row.source_sha256,
        status=row.status,
        counts=report["counts"],
        issue_counts=report["issue_counts"],
        valid=report["valid"],
        import_ready=report["import_ready"],
        created_by=row.created_by,
        created_at=row.created_at,
    )


@router.post("", response_model=LegacyTimetableImportDetail, status_code=status.HTTP_201_CREATED)
async def stage_legacy_timetable_project(request: Request, db: DbSession, claims: Claims) -> LegacyTimetableImportDetail:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != UPLOAD_MEDIA_TYPE:
        raise HTTPException(status_code=415, detail="Upload a .pri package as application/octet-stream")
    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdigit() and int(declared_length) > MAX_ARCHIVE_BYTES:
        raise HTTPException(status_code=413, detail="Legacy timetable package exceeds the upload limit")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_ARCHIVE_BYTES:
            raise HTTPException(status_code=413, detail="Legacy timetable package exceeds the upload limit")
        content.extend(chunk)
    if not content:
        raise HTTPException(status_code=400, detail="Legacy timetable package is empty")

    key_text = get_settings().legacy_pri_key_hex.strip()
    if not key_text:
        raise HTTPException(status_code=503, detail="Legacy timetable decryption key is not configured")
    try:
        key = bytes.fromhex(key_text)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail="Legacy timetable decryption key configuration is invalid") from exc
    try:
        data = read_legacy_pri(bytes(content), key)
    except LegacyPriError as exc:
        raise HTTPException(status_code=422, detail="Legacy timetable package failed archive, decryption or schema validation") from exc

    report = reconcile_legacy_pri(data)
    report_json = json.dumps(report, separators=(",", ":"), sort_keys=True)
    source_bytes = bytes(content)
    source_hash = hashlib.sha256(source_bytes).hexdigest()
    if db.scalar(select(LegacyTimetableImport.id).where(LegacyTimetableImport.source_sha256 == source_hash)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This legacy timetable package has already been staged")
    stage_status = "READY_FOR_IMPORT" if report["import_ready"] else "REVIEW_REQUIRED"
    row = LegacyTimetableImport(
        source_sha256=source_hash,
        source_ciphertext=encrypt_sensitive_bytes(source_bytes),
        report_json=report_json,
        status=stage_status,
        created_by=int(claims["sub"]),
    )
    db.add(row)
    try:
        db.flush()
        record_event(
            db,
            int(claims["sub"]),
            "timetable.legacy_import.staged",
            "legacy_timetable_import",
            str(row.id),
            {"source_sha256": source_hash, "status": stage_status, "counts": report["counts"], "issue_counts": report["issue_counts"]},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This legacy timetable package has already been staged") from exc
    db.refresh(row)
    return LegacyTimetableImportDetail(**_summary(row).model_dump(), issues=report["issues"])


@router.get("", response_model=list[LegacyTimetableImportSummary])
def list_legacy_timetable_imports(
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[LegacyTimetableImportSummary]:
    rows = db.scalars(select(LegacyTimetableImport).order_by(LegacyTimetableImport.id.desc()).offset(offset).limit(limit)).all()
    return [_summary(row) for row in rows]


@router.get("/{import_id}", response_model=LegacyTimetableImportDetail)
def get_legacy_timetable_import(import_id: int, db: DbSession) -> LegacyTimetableImportDetail:
    row = db.get(LegacyTimetableImport, import_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Legacy timetable import not found")
    report = _report(row)
    return LegacyTimetableImportDetail(**_summary(row).model_dump(), issues=report["issues"])


@router.delete("/{import_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_legacy_timetable_import(
    import_id: int,
    db: DbSession,
    claims: Claims,
    confirm: bool = Query(default=False),
) -> None:
    if not confirm:
        raise HTTPException(status_code=400, detail="Set confirm=true to permanently remove staged source data")
    row = db.scalar(select(LegacyTimetableImport).where(LegacyTimetableImport.id == import_id).with_for_update())
    if row is None:
        raise HTTPException(status_code=404, detail="Legacy timetable import not found")
    if row.status == "IMPORTED":
        raise HTTPException(status_code=409, detail="An imported timetable package cannot be removed")
    record_event(
        db,
        int(claims["sub"]),
        "timetable.legacy_import.deleted",
        "legacy_timetable_import",
        str(row.id),
        {"source_sha256": row.source_sha256, "status": row.status},
    )
    db.delete(row)
    db.commit()
