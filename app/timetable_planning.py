"""Snapshot and validate weekly timetable plans for manual and generated drafts."""

import json
from collections import Counter, defaultdict
from datetime import date, time, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.lesson_validation import validate_lesson_resources
from app.models import InstructionalClass, LessonRequirement, Subject, Teacher, TimetablePlacement, TimetableVersion
from app.scheduling_rules import resolve_rules
from app.schemas import WEEKDAYS, LessonRequirementResponse, RuleResolutionRequest
from app.timetable_periods import resolve_period_rows, validate_period_intervals


def build_snapshot(db: Session, academic_year: str, week_start: date, class_ids: list[int]) -> dict:
    rules = {}
    for day_index, weekday in enumerate(WEEKDAYS):
        rules[weekday] = {
            row.instructional_class_id: row.model_dump(mode="json")
            for row in resolve_rules(
                db, RuleResolutionRequest(academic_year=academic_year, on_date=week_start + timedelta(days=day_index), class_ids=class_ids)
            )
        }
    validate_period_intervals(db, class_ids)
    snapshot = {"schema_version": 1, "classes": {}, "requirements": {}, "teachers": {}, "subjects": {}}
    for class_id in sorted(class_ids):
        row = db.get(InstructionalClass, class_id)
        snapshot["classes"][str(class_id)] = {
            "id": class_id,
            "code": row.code,
            "name": row.name,
            "reporting_order": row.reporting_order,
            "periods": [
                {
                    "id": period.id,
                    "slot_code": period.slot_code,
                    "label": period.label,
                    "display_order": period.display_order,
                    "starts_at": period.starts_at,
                    "ends_at": period.ends_at,
                    "is_schedulable": period.is_schedulable,
                }
                for period in resolve_period_rows(db, class_id)
            ],
            "rules": {weekday: rules[weekday][class_id] for weekday in WEEKDAYS},
        }
    requirements = db.scalars(
        select(LessonRequirement)
        .where(
            LessonRequirement.is_active.is_(True),
            LessonRequirement.instructional_class_id.in_(class_ids),
            func.upper(func.trim(LessonRequirement.academic_year)) == academic_year,
        )
        .order_by(LessonRequirement.id)
    ).all()
    for row in requirements:
        payload = LessonRequirementResponse.model_validate(row, from_attributes=True)
        validate_lesson_resources(db, payload)
        snapshot["requirements"][str(row.id)] = payload.model_dump(mode="json")
        teacher = db.get(Teacher, row.teacher_id)
        subject = db.get(Subject, row.subject_id)
        snapshot["teachers"][str(teacher.id)] = {
            "id": teacher.id,
            "short_code": teacher.short_code,
            "full_name": teacher.full_name,
            "is_adjunct": teacher.is_adjunct,
            "availability": json.loads(teacher.availability_json),
        }
        snapshot["subjects"][str(subject.id)] = {
            "id": subject.id,
            "code": subject.code,
            "name": subject.name,
            "description": subject.description,
        }
    return snapshot


def assert_current_snapshot(db: Session, version: TimetableVersion) -> dict:
    snapshot = json.loads(version.snapshot_json)
    current = build_snapshot(db, version.academic_year, version.week_start, [int(key) for key in snapshot["classes"]])
    if current != snapshot:
        raise HTTPException(
            status_code=409, detail="Timetable configuration changed; create a replacement draft using the current configuration"
        )
    return snapshot


def placement_values(row: TimetablePlacement) -> dict:
    return {
        "id": row.id,
        "lesson_requirement_id": row.lesson_requirement_id,
        "weekday": row.weekday,
        "start_period": row.start_period,
        "period_count": row.period_count,
        "is_locked": row.is_locked,
        "note": row.note,
    }


def load_blocks(db: Session, version_id: int) -> list[dict]:
    return [
        placement_values(row)
        for row in db.scalars(
            select(TimetablePlacement).where(TimetablePlacement.version_id == version_id).order_by(TimetablePlacement.id)
        ).all()
    ]


def required_blocks(requirement: dict) -> Counter:
    full, remainder = divmod(requirement["weekly_count"], requirement["block_length"])
    return Counter([requirement["block_length"]] * full + ([remainder] if remainder else []))


def pending_requirements(snapshot: dict, blocks: list[dict]) -> list[dict]:
    placed = defaultdict(Counter)
    for block in blocks:
        placed[str(block["lesson_requirement_id"])][block["period_count"]] += 1
    result = []
    for requirement_id, requirement in snapshot["requirements"].items():
        remaining = required_blocks(requirement) - placed[requirement_id]
        lengths = sorted(remaining.elements(), reverse=True)
        if lengths:
            result.append({"lesson_requirement_id": int(requirement_id), "remaining_periods": sum(lengths), "remaining_blocks": lengths})
    return result


def validate_plan(snapshot: dict, blocks: list[dict], *, require_complete: bool = False) -> dict[int, list[dict]]:
    expanded = {}
    placed = defaultdict(Counter)
    daily_counts = Counter()
    occupied = defaultdict(list)
    for block in blocks:
        requirement = snapshot["requirements"].get(str(block["lesson_requirement_id"]))
        if requirement is None:
            raise HTTPException(status_code=422, detail="Lesson requirement is not part of this timetable snapshot")
        expected = required_blocks(requirement)
        placed[requirement["id"]][block["period_count"]] += 1
        if placed[requirement["id"]][block["period_count"]] > expected[block["period_count"]]:
            raise HTTPException(status_code=409, detail="Placement exceeds the requirement's weekly count or block pattern")
        class_id = requirement["instructional_class_id"]
        teacher_id = requirement["teacher_id"]
        weekday = block["weekday"]
        class_snapshot = snapshot["classes"][str(class_id)]
        rule = class_snapshot["rules"][weekday]["rule"]
        if weekday not in rule["allowed_days"]:
            raise HTTPException(status_code=409, detail="Scheduling rule does not allow this weekday")
        periods = class_snapshot["periods"]
        starts = [index for index, period in enumerate(periods) if period["slot_code"] == block["start_period"]]
        if not starts:
            raise HTTPException(status_code=409, detail="Start period is not configured for the class")
        selection = periods[starts[0] : starts[0] + block["period_count"]]
        if len(selection) != block["period_count"] or any(not period["is_schedulable"] for period in selection):
            raise HTTPException(status_code=409, detail="Lesson blocks cannot cross lunch or the end of the day")
        for previous, current in zip(selection, selection[1:], strict=False):
            if previous["ends_at"] != current["starts_at"]:
                raise HTTPException(status_code=409, detail="Lesson blocks cannot cross a gap between configured periods")
        daily_counts[(class_id, weekday)] += len(selection)
        if daily_counts[(class_id, weekday)] > rule["max_lessons_per_day"]:
            raise HTTPException(status_code=409, detail="Scheduling rule daily lesson limit would be exceeded")
        availability = snapshot["teachers"][str(teacher_id)]["availability"][weekday]
        slots = []
        for period in selection:
            if period["slot_code"] not in rule["allowed_periods"]:
                raise HTTPException(status_code=409, detail="Scheduling rule does not allow this teaching period")
            if period["slot_code"] not in availability:
                raise HTTPException(status_code=409, detail="Teacher is unavailable in this teaching period")
            start, end = time.fromisoformat(period["starts_at"]), time.fromisoformat(period["ends_at"])
            for resource_type, resource_id in (("class", class_id), ("teacher", teacher_id)):
                key = (resource_type, resource_id, weekday)
                if any(start < other_end and other_start < end for other_start, other_end in occupied[key]):
                    raise HTTPException(status_code=409, detail=f"Timetable {resource_type} conflict at the configured time interval")
                occupied[key].append((start, end))
            slots.append(
                {
                    "instructional_class_id": class_id,
                    "teacher_id": teacher_id,
                    "subject_id": requirement["subject_id"],
                    "weekday": weekday,
                    "slot_code": period["slot_code"],
                    "starts_at": start,
                    "ends_at": end,
                }
            )
        expanded[block["id"]] = slots
    pending = pending_requirements(snapshot, blocks)
    if require_complete and pending:
        raise HTTPException(status_code=409, detail={"message": "Timetable has unplaced lesson requirements", "pending": pending})
    return expanded
