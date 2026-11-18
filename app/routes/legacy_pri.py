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
    TimetableFixedEvent,
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
MAX_LEGACY_SOURCE_ROWS = 5000


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
        len(rows) > MAX_LEGACY_SOURCE_ROWS
        for rows in (data.teachers, data.subjects, data.classes, data.lessons, data.placements, data.pending)
    ):
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Legacy project exceeds the source row limit")
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
    if len(rows) > MAX_LEGACY_SOURCE_ROWS:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Legacy project exceeds the source row limit")
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


def _validate_whole_school_event_mappings(
    data: LegacyPriData,
    options: LegacyPriImportOptions,
    db,
    class_ids_by_name: dict[str, int],
) -> None:
    if any(row.get("Teacher") == "ALL" for row in data.lessons):
        raise HTTPException(status_code=422, detail="Whole-school lesson requirements must be reconciled as fixed events")

    subject_indexes: dict[str, list[int]] = defaultdict(list)
    for index, subject in enumerate(data.subjects):
        name = subject.get("Name")
        if isinstance(name, str) and name.strip():
            subject_indexes[name.strip()].append(index)

    event_rows: dict[int, list[dict]] = defaultdict(list)
    for row in data.placements:
        if row.get("Teacher") == "ALL":
            label = row.get("Subject")
            if not isinstance(label, str) or not label.strip():
                raise HTTPException(status_code=422, detail="Every whole-school placement needs an event label")
            matching_subjects = subject_indexes.get(label.strip(), [])
            if len(matching_subjects) != 1:
                raise HTTPException(status_code=422, detail="Every whole-school event label must resolve to one source subject row")
            event_rows[matching_subjects[0]].append(row)

    if set(options.fixed_events) != set(event_rows):
        raise HTTPException(status_code=422, detail="Map each whole-school event label to one fixed event")
    if len(set(options.fixed_events.values())) != len(options.fixed_events):
        raise HTTPException(status_code=422, detail="Each source whole-school event must map to a distinct fixed event")

    imported_class_ids = set(class_ids_by_name.values())
    slot_by_legacy_period = {1: "P1", 2: "P2", 4: "P3", 5: "P4"}
    for source_subject_index, source_rows in event_rows.items():
        event_id = options.fixed_events[source_subject_index]
        event = db.get(TimetableFixedEvent, event_id)
        if event is None or not event.is_active:
            raise HTTPException(status_code=422, detail="Mapped fixed event is missing or inactive")
        if event.audience_type != "CLASS" or event.academic_year.strip().upper() != options.academic_year.strip().upper():
            raise HTTPException(status_code=422, detail="Mapped fixed event must be an active class event for the selected academic year")

        source_classes: set[int] = set()
        source_slots: set[tuple[str, str]] = set()
        for row in source_rows:
            class_name = row.get("InstClass")
            weekday = row.get("DayOfWeek")
            period = row.get("Period")
            class_id = class_ids_by_name.get(class_name.strip()) if isinstance(class_name, str) else None
            weekday_code = {
                "mo": "MON", "mon": "MON", "tu": "TUE", "tue": "TUE", "we": "WED", "wed": "WED",
                "th": "THU", "thu": "THU", "fr": "FRI", "fri": "FRI",
            }.get(weekday.casefold()) if isinstance(weekday, str) else None
            slot_code = slot_by_legacy_period.get(period) if type(period) is int else None
            if class_id is None or weekday_code is None or slot_code is None:
                raise HTTPException(status_code=422, detail="Whole-school source event has an unmappable class, day or teaching period")
            source_classes.add(class_id)
            source_slots.add((weekday_code, slot_code))

        if event.target_mode == "ALL":
            event_classes = imported_class_ids
        else:
            event_classes = set(json.loads(event.target_ids_json)) & imported_class_ids
        event_slots = {(slot["weekday"], slot["slot_code"]) for slot in json.loads(event.slots_json)}
        if event_classes != source_classes or event_slots != source_slots:
            raise HTTPException(
                status_code=422,
                detail=f"Mapped fixed event for source subject row {source_subject_index + 1} must match the source classes and weekday/period slots exactly",
            )


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

    if any(
        len(rows) > MAX_LEGACY_SOURCE_ROWS
        for rows in (data.teachers, data.subjects, data.classes, data.lessons, data.placements, data.pending)
    ):
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Legacy project exceeds the source row limit")
    report = reconcile_legacy_pri(data)
    if not data.classes or not data.lessons or not data.placements:
        raise HTTPException(status_code=422, detail="Legacy project must contain classes, lesson requirements and placements")
    if data.pending:
        raise HTTPException(
            status_code=422,
            detail={"message": "Unplaced legacy records must be reconciled before import", "pending_count": len(data.pending)},
        )
    resolved_by_mapping = {"composite_teacher_mapping_required", "whole_school_event_mapping_required"}
    blockers = {code: count for code, count in report["issue_counts"].items() if code not in resolved_by_mapping}
    if blockers:
        raise HTTPException(status_code=422, detail={"message": "Resolve source validation issues before import", "issue_counts": blockers})
    if any(row.get("Teacher") == "ALL" for row in data.lessons):
        raise HTTPException(status_code=422, detail="Whole-school lesson requirements must be reconciled as fixed events")
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
        _validate_whole_school_event_mappings(data, options, db, class_ids_by_name)
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
            if source.get("Teacher") == "ALL":
                continue
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
            {
                "source_sha256": source_digest,
                "counts": report["counts"],
                "week_start": options.week_start.isoformat(),
                "fixed_event_mappings": {str(source_index): event_id for source_index, event_id in sorted(options.fixed_events.items())},
            },
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
