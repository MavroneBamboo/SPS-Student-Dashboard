"""Shared lesson checks for requirement editing and future timetable placement."""

import json
from datetime import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import InstructionalClass, LessonRequirement, PeriodDefinition, Subject, Teacher
from app.schemas import WEEKDAYS, LessonRequirementCreate, TeacherCreate
from app.timetable_periods import resolve_period_rows, validate_period_intervals


def available_runs(availability: dict[str, list[str]], periods: list[PeriodDefinition]) -> list[int]:
    """Return contiguous run lengths; lunch, unavailable slots and time gaps split runs."""
    runs = []
    for day in WEEKDAYS:
        run_length = 0
        previous_end = None
        for period in periods:
            if not period.is_schedulable or period.slot_code not in availability[day]:
                if run_length:
                    runs.append(run_length)
                run_length = 0
                previous_end = None
                continue
            starts_at = time.fromisoformat(period.starts_at)
            if run_length and previous_end != starts_at:
                runs.append(run_length)
                run_length = 0
            run_length += 1
            previous_end = time.fromisoformat(period.ends_at)
        if run_length:
            runs.append(run_length)
    return runs


def can_fit_weekly_blocks(runs: list[int], weekly_count: int, block_length: int) -> bool:
    """Fit full blocks plus one shorter remainder block without reusing any period."""
    full_blocks, remainder = divmod(weekly_count, block_length)
    reachable = {(0, remainder == 0)}
    for run in runs:
        next_reachable = set(reachable)
        for placed, remainder_placed in reachable:
            for blocks in range(min(run // block_length, full_blocks - placed) + 1):
                next_reachable.add((placed + blocks, remainder_placed))
                if not remainder_placed and blocks * block_length + remainder <= run:
                    next_reachable.add((placed + blocks, True))
        reachable = next_reachable
    return (full_blocks, True) in reachable


def validate_lesson_resources(db: Session, payload: LessonRequirementCreate, *, is_active: bool = True) -> None:
    teacher = db.get(Teacher, payload.teacher_id)
    subject = db.get(Subject, payload.subject_id)
    instructional_class = db.get(InstructionalClass, payload.instructional_class_id)
    for label, resource in (("Teacher", teacher), ("Subject", subject), ("Instructional class", instructional_class)):
        if resource is None:
            raise HTTPException(status_code=422, detail=f"{label} does not exist")
        if is_active and not resource.is_active:
            raise HTTPException(status_code=422, detail=f"{label} is inactive")
    if not is_active:
        return
    try:
        availability = TeacherCreate(
            short_code=teacher.short_code,
            full_name=teacher.full_name,
            availability=json.loads(teacher.availability_json),
        ).availability
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="Teacher availability needs correction before lesson planning") from exc
    validate_period_intervals(db, [instructional_class.id])
    periods = resolve_period_rows(db, instructional_class.id)
    runs = available_runs(availability, periods)
    if not can_fit_weekly_blocks(runs, payload.weekly_count, payload.block_length):
        raise HTTPException(
            status_code=422,
            detail={"message": "Teacher availability cannot accommodate this requirement's blocks", "available_periods": sum(runs)},
        )


def validate_existing_class_lessons(db: Session, class_ids: list[int]) -> None:
    requirements = db.scalars(
        select(LessonRequirement).where(LessonRequirement.is_active.is_(True), LessonRequirement.instructional_class_id.in_(class_ids))
    ).all()
    for row in requirements:
        try:
            validate_lesson_resources(db, LessonRequirementCreate.model_validate(row, from_attributes=True))
        except HTTPException as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Period configuration would invalidate an active lesson requirement",
                    "lesson_id": row.id,
                    "reason": exc.detail,
                },
            ) from exc
