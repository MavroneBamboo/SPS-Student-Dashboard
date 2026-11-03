import json
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.config import get_settings
from app.crypto import decrypt_sensitive, decrypt_sensitive_bytes, encrypt_sensitive, encrypt_sensitive_bytes
from app.deps import Claims, DbSession, require_roles
from app.models import InstructionalClass, Student, StudentClassMapping, StudentImportBatch, StudentStatusHistory
from app.routes.students import ENCRYPTED_PROFILE_FIELDS, PLAIN_PROFILE_FIELDS
from app.student_class_mapping import STUDENT_INTAKE_2023, normalize_source_class_label
from app.student_import import MAX_UPLOAD_BYTES, ImportFileError, mark_duplicate_identifiers, parse_student_workbook

router = APIRouter(prefix="/student-imports", tags=["student imports"])
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ImportRowError(BaseModel):
    row_number: int
    field: str
    code: str


class ImportRowWarning(BaseModel):
    row_number: int
    field: str
    code: str


class ImportBatchResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    status: str
    row_count: int
    valid_count: int
    invalid_count: int
    warning_count: int
    existing_count: int
    new_count: int
    row_errors: list[ImportRowError]
    row_warnings: list[ImportRowWarning]
    result: dict | None = None
    expired: bool
    payload_available: bool
    payload_purged_at: datetime | None


class ImportRetentionResponse(BaseModel):
    retention_days: int
    enabled: bool
    eligible_batches: int
    eligible_preview_batches: int
    eligible_committed_batches: int
    oldest_eligible_created_at: datetime | None


class ImportRetentionPurgeRequest(BaseModel):
    apply: bool = False


class ImportRetentionPurgeResponse(ImportRetentionResponse):
    applied: bool
    purged_batches: int


class ImportCommitRequest(BaseModel):
    mode: Literal["CREATE_ONLY", "UPDATE_EXISTING"]
    confirm_data_warnings: bool = False


def _safe_batch_view(batch: StudentImportBatch) -> ImportBatchResponse:
    try:
        staged = json.loads(decrypt_sensitive_bytes(batch.rows_ciphertext)) if batch.rows_ciphertext is not None else []
        result = json.loads(batch.result_json) if batch.result_json else None
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Stored import batch could not be read") from exc
    errors = [
        ImportRowError(row_number=row["row_number"], field=error["field"], code=error["code"]) for row in staged for error in row["errors"]
    ]
    warnings = [
        ImportRowWarning(row_number=row["row_number"], field=warning["field"], code=warning["code"])
        for row in staged
        for warning in row["warnings"]
    ]
    return ImportBatchResponse(
        id=batch.id,
        status=batch.status,
        row_count=batch.row_count,
        valid_count=batch.valid_count,
        invalid_count=batch.invalid_count,
        warning_count=batch.warning_count,
        existing_count=batch.existing_count,
        new_count=batch.new_count,
        row_errors=errors,
        row_warnings=warnings,
        result=result,
        expired=_is_retention_expired(batch.created_at),
        payload_available=batch.source_ciphertext is not None and batch.rows_ciphertext is not None,
        payload_purged_at=batch.payload_purged_at,
    )


def _retention_cutoff(now: datetime | None = None) -> datetime | None:
    days = get_settings().student_import_retention_days
    return (now or datetime.now(UTC)) - timedelta(days=days) if days else None


def _is_retention_expired(created_at: datetime, now: datetime | None = None) -> bool:
    cutoff = _retention_cutoff(now)
    if cutoff is None:
        return False
    if created_at.tzinfo is None and cutoff.tzinfo is not None:
        created_at = created_at.replace(tzinfo=UTC)
    return created_at <= cutoff


def _eligible_import_batches(db: DbSession, cutoff: datetime):
    return db.scalars(
        select(StudentImportBatch)
        .where(
            StudentImportBatch.created_at <= cutoff,
            StudentImportBatch.payload_purged_at.is_(None),
            or_(StudentImportBatch.source_ciphertext.is_not(None), StudentImportBatch.rows_ciphertext.is_not(None)),
        )
        .order_by(StudentImportBatch.id)
    ).all()


def _retention_summary(db: DbSession, cutoff: datetime | None) -> dict:
    if cutoff is None:
        return {
            "retention_days": get_settings().student_import_retention_days,
            "enabled": False,
            "eligible_batches": 0,
            "eligible_preview_batches": 0,
            "eligible_committed_batches": 0,
            "oldest_eligible_created_at": None,
        }
    rows = _eligible_import_batches(db, cutoff)
    return {
        "retention_days": get_settings().student_import_retention_days,
        "enabled": True,
        "eligible_batches": len(rows),
        "eligible_preview_batches": sum(row.status == "PREVIEW" for row in rows),
        "eligible_committed_batches": sum(row.status == "COMMITTED" for row in rows),
        "oldest_eligible_created_at": min((row.created_at for row in rows), default=None),
    }


@router.get("/retention", response_model=ImportRetentionResponse, dependencies=[Depends(require_roles("Superuser", "IT Administrator"))])
def student_import_retention_status(db: DbSession) -> ImportRetentionResponse:
    return ImportRetentionResponse(**_retention_summary(db, _retention_cutoff()))


@router.post(
    "/retention/purge",
    response_model=ImportRetentionPurgeResponse,
    dependencies=[Depends(require_roles("Superuser", "IT Administrator"))],
)
def purge_expired_student_import_payloads(
    payload: ImportRetentionPurgeRequest, db: DbSession, claims: Claims
) -> ImportRetentionPurgeResponse:
    cutoff = _retention_cutoff()
    if cutoff is None:
        raise HTTPException(status_code=409, detail="Student import retention is disabled; configure STUDENT_IMPORT_RETENTION_DAYS")
    summary = _retention_summary(db, cutoff)
    purged = 0
    if payload.apply and summary["eligible_batches"]:
        rows = db.scalars(
            select(StudentImportBatch)
            .where(
                StudentImportBatch.created_at <= cutoff,
                StudentImportBatch.payload_purged_at.is_(None),
                or_(StudentImportBatch.source_ciphertext.is_not(None), StudentImportBatch.rows_ciphertext.is_not(None)),
            )
            .order_by(StudentImportBatch.id)
            .with_for_update()
        ).all()
        now = datetime.now(UTC)
        actor_id = int(claims["sub"])
        for batch in rows:
            previous_status = batch.status
            batch.source_ciphertext = None
            batch.rows_ciphertext = None
            batch.payload_purged_at = now
            if batch.status == "PREVIEW":
                batch.status = "EXPIRED"
            record_event(
                db,
                actor_id,
                "student.import_payload.purged",
                "student_import_batch",
                str(batch.id),
                {"previous_status": previous_status, "row_count": batch.row_count},
            )
            purged += 1
        db.commit()
        summary = _retention_summary(db, cutoff)
    return ImportRetentionPurgeResponse(**summary, applied=payload.apply, purged_batches=purged)


def _load_owned_batch(db, batch_id: int, actor_id: int, *, lock: bool = False) -> StudentImportBatch:
    query = select(StudentImportBatch).where(StudentImportBatch.id == batch_id, StudentImportBatch.created_by == actor_id)
    if lock:
        query = query.with_for_update()
    batch = db.scalar(query)
    if batch is None:
        raise HTTPException(status_code=404, detail="Import batch not found")
    return batch


def _stored_fields(row: Student) -> dict:
    values = {field: getattr(row, field) for field in PLAIN_PROFILE_FIELDS}
    values.update({field: decrypt_sensitive(getattr(row, column)) for field, column in ENCRYPTED_PROFILE_FIELDS.items()})
    values.update(
        {
            "pris_no": row.pris_no,
            "name": decrypt_sensitive(row.name_encrypted),
            "class_name": row.class_name,
            "category": row.category,
            "status": row.status,
            "status_effective": row.status_effective.isoformat() if row.status_effective else None,
            "date_of_birth": decrypt_sensitive(row.date_of_birth_encrypted),
        }
    )
    return values


def _database_values(fields: dict) -> dict:
    values = {field: fields.get(field) for field in PLAIN_PROFILE_FIELDS if field in fields}
    values.update({column: encrypt_sensitive(fields.get(field)) for field, column in ENCRYPTED_PROFILE_FIELDS.items() if field in fields})
    if "name" in fields:
        values["name_encrypted"] = encrypt_sensitive(fields["name"])
    if "date_of_birth" in fields:
        value = fields["date_of_birth"]
        values["date_of_birth_encrypted"] = encrypt_sensitive(value)
    return values


@router.post(
    "",
    response_model=ImportBatchResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("Operator", "Superuser"))],
)
async def upload_student_workbook(request: Request, db: DbSession, claims: Claims) -> ImportBatchResponse:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != XLSX_MEDIA_TYPE:
        raise HTTPException(status_code=415, detail="Upload an .xlsx Student Intake workbook")
    declared_length = request.headers.get("content-length")
    if declared_length and declared_length.isdigit() and int(declared_length) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Workbook exceeds the upload limit")
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Workbook exceeds the upload limit")
        content.extend(chunk)
    if not content:
        raise HTTPException(status_code=400, detail="Workbook is empty")
    source = bytes(content)
    try:
        rows = parse_student_workbook(source)
    except ImportFileError as exc:
        if exc.code == "file_too_large":
            raise HTTPException(status_code=413, detail="Workbook exceeds the upload limit") from exc
        raise HTTPException(status_code=422, detail=f"Workbook could not be imported ({exc.code})") from exc

    try:
        mark_duplicate_identifiers(rows)
        mapping_rows = db.execute(
            select(StudentClassMapping, InstructionalClass)
            .join(InstructionalClass, InstructionalClass.id == StudentClassMapping.instructional_class_id)
            .where(StudentClassMapping.source_workbook == STUDENT_INTAKE_2023)
        ).all()
        mappings_by_key = {mapping.source_key: (mapping, instructional_class) for mapping, instructional_class in mapping_rows}
        for row in rows:
            source_label = row["fields"].get("class_name")
            if not source_label:
                continue
            normalized_label, source_key = normalize_source_class_label(source_label)
            row["source_class_label"] = normalized_label
            mapping_target = mappings_by_key.get(source_key)
            if mapping_target is None or not mapping_target[0].is_active or not mapping_target[1].is_active:
                row["errors"].append({"field": "class_name", "code": "unmapped_class"})
                continue
            mapping, instructional_class = mapping_target
            row["class_mapping_id"] = mapping.id
            row["class_mapping_version"] = mapping.version
            row["instructional_class_id"] = instructional_class.id
            row["fields"]["class_name"] = instructional_class.name
        identifiers = {row["fields"].get("pris_no", "").strip().upper() for row in rows if row["fields"].get("pris_no")}
        existing = db.scalars(select(Student).where(func.upper(func.trim(Student.pris_no)).in_(identifiers))).all() if identifiers else []
        existing_by_identifier = {row.pris_no.strip().upper(): row for row in existing}
        for row in rows:
            pris_no = row["fields"].get("pris_no")
            saved = existing_by_identifier.get(pris_no.strip().upper()) if pris_no else None
            row["existing_student_id"] = saved.id if saved else None
            row["expected_version"] = saved.version if saved else None
            if saved is None:
                for field in ("name", "class_name", "category", "status"):
                    if row["fields"].get(field) is None:
                        row["errors"].append({"field": field, "code": "required_for_new_profile"})
        valid_rows = [row for row in rows if not row["errors"]]
        existing_count = sum(row["existing_student_id"] is not None for row in valid_rows)
        batch = StudentImportBatch(
            status="PREVIEW",
            source_ciphertext=encrypt_sensitive_bytes(source),
            rows_ciphertext=encrypt_sensitive_bytes(json.dumps(rows, separators=(",", ":"), sort_keys=True).encode()),
            row_count=len(rows),
            valid_count=len(valid_rows),
            invalid_count=len(rows) - len(valid_rows),
            warning_count=sum(len(row["warnings"]) for row in rows),
            existing_count=existing_count,
            new_count=len(valid_rows) - existing_count,
            created_by=int(claims["sub"]),
        )
        db.add(batch)
        db.flush()
        record_event(
            db,
            int(claims["sub"]),
            "student.import_batch.created",
            "student_import_batch",
            str(batch.id),
            {
                "row_count": batch.row_count,
                "valid_count": batch.valid_count,
                "invalid_count": batch.invalid_count,
                "warning_count": batch.warning_count,
            },
        )
        db.commit()
        db.refresh(batch)
        return _safe_batch_view(batch)
    finally:
        content.clear()


@router.get("/{batch_id}", response_model=ImportBatchResponse, dependencies=[Depends(require_roles("Operator", "Superuser"))])
def get_student_import(batch_id: int, db: DbSession, claims: Claims) -> ImportBatchResponse:
    return _safe_batch_view(_load_owned_batch(db, batch_id, int(claims["sub"])))


@router.post("/{batch_id}/commit", response_model=ImportBatchResponse, dependencies=[Depends(require_roles("Operator", "Superuser"))])
def commit_student_import(batch_id: int, payload: ImportCommitRequest, db: DbSession, claims: Claims) -> ImportBatchResponse:
    actor_id = int(claims["sub"])
    batch = _load_owned_batch(db, batch_id, actor_id, lock=True)
    if batch.status == "COMMITTED":
        return _safe_batch_view(batch)
    if batch.status == "EXPIRED" or batch.payload_purged_at is not None or batch.rows_ciphertext is None:
        raise HTTPException(status_code=409, detail="Import preview has expired and its staged data was purged")
    if _is_retention_expired(batch.created_at):
        raise HTTPException(status_code=409, detail="Import preview has expired; it can no longer be committed")
    if batch.invalid_count:
        raise HTTPException(status_code=409, detail="Resolve all invalid workbook rows before committing")
    if batch.warning_count and not payload.confirm_data_warnings:
        raise HTTPException(status_code=409, detail="Confirm the workbook data warnings before committing")
    try:
        staged = json.loads(decrypt_sensitive_bytes(batch.rows_ciphertext))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=500, detail="Stored import batch could not be read") from exc

    identifiers = [row["fields"]["pris_no"].strip().upper() for row in staged]
    mapping_ids = [row["class_mapping_id"] for row in staged if row.get("class_mapping_id") is not None]
    current_mappings = (
        {
            mapping.id: (mapping, instructional_class)
            for mapping, instructional_class in db.execute(
                select(StudentClassMapping, InstructionalClass)
                .join(InstructionalClass, InstructionalClass.id == StudentClassMapping.instructional_class_id)
                .where(StudentClassMapping.id.in_(mapping_ids))
                .with_for_update()
            ).all()
        }
        if mapping_ids
        else {}
    )
    for staged_row in staged:
        mapping_id = staged_row.get("class_mapping_id")
        if mapping_id is None:
            continue
        mapping_pair = current_mappings.get(mapping_id)
        mapping, instructional_class = mapping_pair if mapping_pair else (None, None)
        if (
            mapping is None
            or not mapping.is_active
            or mapping.version != staged_row["class_mapping_version"]
            or mapping.instructional_class_id != staged_row["instructional_class_id"]
            or instructional_class is None
            or not instructional_class.is_active
            or instructional_class.name != staged_row["fields"]["class_name"]
        ):
            db.rollback()
            raise HTTPException(status_code=409, detail="A class mapping changed after preview; upload the workbook again")
    current_rows = db.scalars(select(Student).where(func.upper(func.trim(Student.pris_no)).in_(identifiers)).with_for_update()).all()
    current = {row.pris_no.strip().upper(): row for row in current_rows}
    for staged_row in staged:
        key = staged_row["fields"]["pris_no"].strip().upper()
        student = current.get(key)
        if staged_row["existing_student_id"] is None:
            if student is not None:
                db.rollback()
                raise HTTPException(status_code=409, detail="Student identifiers changed after preview; upload the workbook again")
        elif student is None or student.id != staged_row["existing_student_id"] or student.version != staged_row["expected_version"]:
            db.rollback()
            raise HTTPException(status_code=409, detail="A student profile changed after preview; upload the workbook again")
    if payload.mode == "CREATE_ONLY" and current:
        raise HTTPException(status_code=409, detail="Existing student identifiers require explicit update-existing mode")

    created = updated = unchanged = 0
    try:
        for staged_row in staged:
            fields = staged_row["fields"]
            key = fields["pris_no"].strip().upper()
            student = current.get(key)
            if student is None:
                values = _database_values(fields)
                student = Student(
                    pris_no=key,
                    class_name=fields["class_name"].strip(),
                    category=fields["category"].strip(),
                    status=fields["status"].strip().upper(),
                    status_effective=date.fromisoformat(fields["status_effective"]) if fields.get("status_effective") else None,
                    created_by=actor_id,
                    **{k: v for k, v in values.items() if k not in {"class_name", "category", "status", "status_effective"}},
                )
                db.add(student)
                db.flush()
                db.add(
                    StudentStatusHistory(
                        student_id=student.id,
                        previous_status=None,
                        new_status=student.status,
                        effective_date=student.status_effective or date.today(),
                        changed_by=actor_id,
                    )
                )
                record_event(
                    db,
                    actor_id,
                    "student.imported",
                    "student",
                    str(student.id),
                    {
                        "fields": sorted(fields.keys()),
                        "import_batch_id": batch.id,
                        "source_row": staged_row["row_number"],
                        "version": student.version,
                    },
                )
                created += 1
                current[key] = student
                continue

            previous = _stored_fields(student)
            changes = {
                field: value for field, value in fields.items() if value is not None and field not in {"pris_no", "status_effective"}
            }
            next_status = str(fields.get("status") or student.status).strip().upper()
            status_changed = fields.get("status") is not None and next_status != student.status
            if status_changed:
                changes["status"] = next_status
                changes["status_effective"] = fields.get("status_effective") or date.today().isoformat()
            changed_fields = {field: value for field, value in changes.items() if value != previous.get(field)}
            if not changed_fields:
                unchanged += 1
                continue
            db_values = _database_values(changed_fields)
            if "class_name" in changed_fields:
                db_values["class_name"] = changed_fields["class_name"].strip()
            if "category" in changed_fields:
                db_values["category"] = changed_fields["category"].strip()
            if "status" in changed_fields:
                db_values["status"] = next_status
            if "status_effective" in changed_fields:
                db_values["status_effective"] = date.fromisoformat(changed_fields["status_effective"])
            old_version = student.version
            changed = db.execute(
                update(Student)
                .where(Student.id == student.id, Student.version == old_version)
                .values(**db_values, version=Student.version + 1)
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise HTTPException(status_code=409, detail="A student profile changed during import; upload the workbook again")
            if status_changed:
                db.add(
                    StudentStatusHistory(
                        student_id=student.id,
                        previous_status=student.status,
                        new_status=next_status,
                        effective_date=db_values.get("status_effective", student.status_effective or date.today()),
                        changed_by=actor_id,
                    )
                )
            record_event(
                db,
                actor_id,
                "student.import_updated",
                "student",
                str(student.id),
                {
                    "fields": sorted(changed_fields),
                    "import_batch_id": batch.id,
                    "previous_version": old_version,
                    "source_row": staged_row["row_number"],
                    "version": old_version + 1,
                },
            )
            updated += 1

        result = {
            "mode": payload.mode,
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "data_warnings_acknowledged": bool(batch.warning_count),
        }
        batch.status = "COMMITTED"
        batch.committed_at = datetime.now(UTC)
        batch.result_json = json.dumps(result, separators=(",", ":"), sort_keys=True)
        record_event(db, actor_id, "student.import_batch.committed", "student_import_batch", str(batch.id), result)
        db.commit()
        db.refresh(batch)
        return _safe_batch_view(batch)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A student identifier changed during import; upload the workbook again") from exc
    except Exception:
        db.rollback()
        raise
