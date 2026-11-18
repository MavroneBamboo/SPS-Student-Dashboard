import hashlib
import json
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.config import get_settings
from app.deps import Claims, DbSession, require_roles
from app.legacy_pri import (
    LegacyPriData,
    LegacyPriError,
    map_legacy_availability,
    read_legacy_pri_bytes,
    reconcile_legacy_pri,
)
from app.lesson_validation import validate_lesson_resources
from app.models import (
    InstructionalClass,
    LegacyTimetableImport,
    LessonRequirement,
    Subject,
    Teacher,
    TeacherGroupMember,
    TimetablePlacement,
    TimetableSlot,
    TimetableVersion,
    TimetableVersionClass,
)
from app.schemas import LegacyPriImportOptions, LessonRequirementCreate
from app.timetable_lock import lock_timetable_configuration
from app.timetable_planning import build_snapshot, required_blocks, validate_plan

router = APIRouter(
    prefix="/timetable/legacy-projects",
    tags=["legacy timetable reconciliation"],
    dependencies=[Depends(require_roles("Superuser", "IT Administrator"))],
)
MAX_LEGACY_PROJECT_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_LEGACY_IMPORT_OPTIONS_BYTES = 256 * 1024
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

    if any(
        len(rows) > MAX_INSPECT_ROWS
        for rows in (data.teachers, data.subjects, data.classes, data.lessons, data.placements, data.pending)
    ):
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Legacy project has too many rows to inspect")
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


def _source_placements(rows: list[dict]) -> list[dict]:
    return [
        {
            "source_index": index,
            "class": row.get("InstClass") if isinstance(row.get("InstClass"), str) else None,
            "teacher": row.get("Teacher") if isinstance(row.get("Teacher"), str) else None,
            "subject": row.get("Subject") if isinstance(row.get("Subject"), str) else None,
            "weekday": row.get("DayOfWeek") if isinstance(row.get("DayOfWeek"), str) else None,
            "period": row.get("Period") if type(row.get("Period")) is int else None,
        }
        for index, row in enumerate(rows)
    ]


@router.post("/inspect")
async def inspect_legacy_project(request: Request, db: DbSession, claims: Claims) -> dict:
    """Show source labels to IT/Superuser for explicit resource reconciliation."""
    data, report = await _read_project(request)
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
        "placements": _source_placements(data.placements),
    }


def _active_target(db, model, target_id: int, label: str):
    target = db.get(model, target_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=422, detail=f"Mapped {label} is missing or inactive")
    return target


def _mapped_teacher(data: LegacyPriData, options: LegacyPriImportOptions, db, source_name: str) -> Teacher:
    if source_name == "ALL":
        raise HTTPException(status_code=422, detail="Whole-school entries require fixed-event reconciliation before import")
    if "/" in source_name:
        group_id = options.teacher_groups.get(source_name)
        if group_id is None:
            raise HTTPException(status_code=422, detail="Composite teacher reference has no explicit group mapping")
        group = _active_target(db, Teacher, group_id, "teacher group")
        if not group.is_composite:
            raise HTTPException(status_code=422, detail="Composite teacher source must map to a composite teacher group")
        names = [part.strip() for part in source_name.split("/")]
        source_member_ids = {
            options.teachers[index] for index, row in enumerate(data.teachers) if row.get("Name") in names and index in options.teachers
        }
        target_member_ids = set(
            db.scalars(select(TeacherGroupMember.member_teacher_id).where(TeacherGroupMember.group_teacher_id == group.id)).all()
        )
        if len(source_member_ids) != len(names) or source_member_ids != target_member_ids:
            raise HTTPException(status_code=422, detail="Mapped group members do not match the source teacher reference")
        return group

    indexes = [index for index, row in enumerate(data.teachers) if row.get("Name") == source_name]
    if len(indexes) != 1 or indexes[0] not in options.teachers:
        raise HTTPException(status_code=422, detail="Teacher reference has no unique explicit mapping")
    index = indexes[0]
    teacher = _active_target(db, Teacher, options.teachers[index], "teacher")
    if teacher.is_composite:
        raise HTTPException(status_code=422, detail="An individual source teacher must map to an individual profile")
    availability = map_legacy_availability(data.teachers[index].get("Availability", ""))
    if availability is None or json.loads(teacher.availability_json) != availability:
        raise HTTPException(status_code=422, detail="Mapped teacher availability does not match the verified legacy profile")
    return teacher


def _pack_source_slots(requirement: LessonRequirement, rows: list[tuple[str, int]]) -> list[dict]:
    if len(rows) != requirement.weekly_count:
        raise HTTPException(status_code=422, detail="Source placement totals do not match the lesson requirement")
    expected = required_blocks({"weekly_count": requirement.weekly_count, "block_length": requirement.block_length})
    # Numeric legacy period 3 is lunch; the other values retain this chronological order.
    period_by_position = {0: "P1", 1: "P2", 2: "P3", 3: "P4"}
    position_by_period = {1: 0, 2: 1, 4: 2, 5: 3}
    available: dict[str, set[int]] = defaultdict(set)
    for weekday, legacy_period in rows:
        if legacy_period not in position_by_period:
            raise HTTPException(status_code=422, detail="Lunch or invalid-period rows cannot be imported as lessons")
        position = position_by_period[legacy_period]
        if position in available[weekday]:
            raise HTTPException(status_code=422, detail="Duplicate source lesson slot")
        available[weekday].add(position)
    packed = []
    for length in sorted(expected.elements(), reverse=True):
        found = None
        for weekday in sorted(available):
            for start in sorted(available[weekday]):
                run = set(range(start, start + length))
                if run <= available[weekday]:
                    found = (weekday, start, run)
                    break
            if found:
                break
        if found is None:
            raise HTTPException(status_code=422, detail="Source placements cannot be grouped into the configured lesson block lengths")
        weekday, start, run = found
        available[weekday].difference_update(run)
        packed.append({"weekday": weekday, "start_period": period_by_position[start], "period_count": length})
    if any(positions for positions in available.values()):
        raise HTTPException(status_code=422, detail="Source placements exceed the configured lesson block pattern")
    return packed


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_legacy_project(request: Request, db: DbSession, claims: Claims) -> dict:
    """Create a validated draft from a source project and explicit resource mappings."""
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/vnd.sps.legacy-pri-import":
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Upload an SPS legacy import envelope")
    declared_length = request.headers.get("content-length")
    max_request_bytes = MAX_LEGACY_PROJECT_UPLOAD_BYTES + MAX_LEGACY_IMPORT_OPTIONS_BYTES + 1
    if declared_length and declared_length.isdigit() and int(declared_length) > max_request_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Legacy import request exceeds the upload limit")

    envelope = bytearray()
    async for chunk in request.stream():
        if len(envelope) + len(chunk) > max_request_bytes:
            raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Legacy import request exceeds the upload limit")
        envelope.extend(chunk)
    if not envelope:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Legacy project is empty")
    options_bytes, separator, archive = envelope.partition(b"\n")
    if not separator or len(options_bytes) > MAX_LEGACY_IMPORT_OPTIONS_BYTES:
        envelope.clear()
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Legacy import options are missing or exceed the upload limit"
        )
    if not archive or len(archive) > MAX_LEGACY_PROJECT_UPLOAD_BYTES:
        envelope.clear()
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Legacy project is empty or exceeds the upload limit")
    source_digest = hashlib.sha256(archive).hexdigest()
    try:
        options = LegacyPriImportOptions.model_validate_json(options_bytes)
        key_hex = get_settings().legacy_pri_key_hex.strip()
        if not key_hex:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Legacy project import is not configured")
        data = read_legacy_pri_bytes(archive, bytes.fromhex(key_hex))
    except HTTPException:
        raise
    except (ValueError, ValidationError, LegacyPriError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Legacy import options or project are invalid"
        ) from exc
    finally:
        envelope.clear()

    report = reconcile_legacy_pri(data)
    if any(
        len(rows) > MAX_INSPECT_ROWS for rows in (data.teachers, data.subjects, data.classes, data.lessons, data.placements, data.pending)
    ):
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Legacy project has too many rows to import")
    if not data.classes or not data.lessons or not data.placements:
        raise HTTPException(status_code=422, detail="Legacy project must contain classes, lesson requirements and placements")
    if data.pending:
        raise HTTPException(
            status_code=422,
            detail={"message": "Unplaced legacy records must be reconciled before import", "pending_count": len(data.pending)},
        )
    blockers = {code: count for code, count in report["issue_counts"].items() if code != "composite_teacher_mapping_required"}
    if blockers:
        raise HTTPException(status_code=422, detail={"message": "Resolve source validation issues before import", "issue_counts": blockers})
    if any(row.get("Teacher") == "ALL" for row in [*data.lessons, *data.placements]):
        raise HTTPException(status_code=422, detail="Whole-school entries require fixed-event reconciliation before import")
    if (
        set(options.teachers) != set(range(len(data.teachers)))
        or set(options.subjects) != set(range(len(data.subjects)))
        or set(options.classes) != set(range(len(data.classes)))
    ):
        raise HTTPException(status_code=422, detail="Every source teacher, subject and class needs an explicit mapping")
    if db.scalar(
        select(LegacyTimetableImport.id).where(
            LegacyTimetableImport.source_sha256 == source_digest,
            LegacyTimetableImport.academic_year == options.academic_year,
            LegacyTimetableImport.week_start == options.week_start,
        )
    ):
        raise HTTPException(status_code=409, detail="This source project was already imported for that academic week")

    for mapping, model, label in (
        (options.teachers, Teacher, "teacher"),
        (options.subjects, Subject, "subject"),
        (options.classes, InstructionalClass, "class"),
    ):
        if len(set(mapping.values())) != len(mapping):
            raise HTTPException(status_code=422, detail=f"Each source {label} must map to a distinct target")
        for target_id in mapping.values():
            _active_target(db, model, target_id, label)

    class_ids_by_name = {row["Name"].strip(): options.classes[index] for index, row in enumerate(data.classes)}
    subject_ids_by_name = {row["Name"].strip(): options.subjects[index] for index, row in enumerate(data.subjects)}
    requirements_by_source: dict[int, LessonRequirement] = {}
    requirement_source_by_target: dict[tuple[int, int, int], int] = {}
    actor_id = int(claims["sub"])
    lock_timetable_configuration(db)
    try:
        for source_index, source in enumerate(data.lessons):
            teacher = _mapped_teacher(data, options, db, source["Teacher"])
            class_id = class_ids_by_name[source["InstClass"].strip()]
            subject_id = subject_ids_by_name[source["Subject"].strip()]
            key = (class_id, teacher.id, subject_id)
            if key in requirement_source_by_target:
                raise HTTPException(status_code=422, detail="Multiple source requirements map to the same application requirement")
            requirement_source_by_target[key] = source_index
            payload = LessonRequirementCreate(
                academic_year=options.academic_year,
                instructional_class_id=class_id,
                teacher_id=teacher.id,
                subject_id=subject_id,
                weekly_count=source["Count"],
                block_length=source["Length"],
            )
            validate_lesson_resources(db, payload)
            existing = db.scalar(
                select(LessonRequirement).where(
                    LessonRequirement.academic_year == options.academic_year,
                    LessonRequirement.instructional_class_id == class_id,
                    LessonRequirement.teacher_id == teacher.id,
                    LessonRequirement.subject_id == subject_id,
                )
            )
            if existing:
                if not existing.is_active or (existing.weekly_count, existing.block_length) != (payload.weekly_count, payload.block_length):
                    raise HTTPException(status_code=409, detail="An existing lesson requirement conflicts with the source project")
                requirement = existing
            else:
                requirement = LessonRequirement(**payload.model_dump(), is_active=True, version=1, created_by=actor_id, updated_by=actor_id)
                db.add(requirement)
                db.flush()
            requirements_by_source[source_index] = requirement

        source_slots: dict[int, list[tuple[str, int]]] = defaultdict(list)
        for source in data.placements:
            teacher = _mapped_teacher(data, options, db, source["Teacher"])
            key = (
                class_ids_by_name[source["InstClass"].strip()],
                teacher.id,
                subject_ids_by_name[source["Subject"].strip()],
            )
            source_index = requirement_source_by_target.get(key)
            if source_index is None:
                raise HTTPException(status_code=422, detail="A source placement has no mapped lesson requirement")
            day = {
                "mo": "MON",
                "mon": "MON",
                "tu": "TUE",
                "tue": "TUE",
                "we": "WED",
                "wed": "WED",
                "th": "THU",
                "thu": "THU",
                "fr": "FRI",
                "fri": "FRI",
            }.get(source["DayOfWeek"].casefold())
            if day is None:
                raise HTTPException(status_code=422, detail="Source weekday cannot be mapped")
            source_slots[requirements_by_source[source_index].id].append((day, source["Period"]))

        blocks = []
        for requirement in requirements_by_source.values():
            for block in _pack_source_slots(requirement, source_slots.pop(requirement.id, [])):
                blocks.append(
                    {
                        "id": -(len(blocks) + 1),
                        "lesson_requirement_id": requirement.id,
                        **block,
                        "is_locked": False,
                        "note": "Imported from legacy timetable",
                    }
                )
        if source_slots:
            raise HTTPException(status_code=422, detail="Source placements map to unmatched requirements")

        target_class_ids = sorted(set(options.classes.values()))
        snapshot = build_snapshot(db, options.academic_year, options.week_start, target_class_ids)
        expanded = validate_plan(snapshot, blocks)
        version = TimetableVersion(
            name=options.name,
            academic_year=options.academic_year,
            week_start=options.week_start,
            status="DRAFT",
            revision=1,
            snapshot_json=json.dumps(snapshot, separators=(",", ":"), sort_keys=True),
            created_by=actor_id,
        )
        db.add(version)
        db.flush()
        db.add_all([TimetableVersionClass(version_id=version.id, instructional_class_id=class_id) for class_id in target_class_ids])
        for block in blocks:
            placement = TimetablePlacement(
                version_id=version.id,
                lesson_requirement_id=block["lesson_requirement_id"],
                weekday=block["weekday"],
                start_period=block["start_period"],
                period_count=block["period_count"],
                is_locked=False,
                note=block["note"],
                created_by=actor_id,
                updated_by=actor_id,
            )
            db.add(placement)
            db.flush()
            db.add_all([TimetableSlot(**slot, placement_id=placement.id, version_id=version.id) for slot in expanded[block["id"]]])
        db.add(
            LegacyTimetableImport(
                source_sha256=source_digest,
                academic_year=options.academic_year,
                week_start=options.week_start,
                timetable_version_id=version.id,
                imported_by=actor_id,
            )
        )
        record_event(
            db,
            actor_id,
            "timetable.legacy_project.imported",
            "timetable_version",
            str(version.id),
            {"source_sha256": source_digest, "counts": report["counts"], "week_start": options.week_start.isoformat()},
        )
        db.commit()
        return {
            "version_id": version.id,
            "name": version.name,
            "academic_year": version.academic_year,
            "week_start": version.week_start,
            "status": version.status,
            "revision": version.revision,
            "placement_count": len(blocks),
            "class_ids": target_class_ids,
        }
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Legacy project conflicts with existing timetable data or was imported concurrently"
        ) from exc
    except Exception:
        db.rollback()
        raise
