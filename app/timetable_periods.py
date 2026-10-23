"""Resolve the shared period pattern for resource setup and timetable planning."""

from datetime import time

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.models import ClassClusterMember, InstructionalClass, PeriodDefinition


def resolve_period_rows(db: Session, instructional_class_id: int) -> list[PeriodDefinition]:
    defaults = db.scalars(select(PeriodDefinition).where(PeriodDefinition.scope == "DEFAULT", PeriodDefinition.is_active.is_(True))).all()
    if len(defaults) != 5 or {row.slot_code for row in defaults} != {"P1", "P2", "LUNCH", "P3", "P4"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Default period pattern is incomplete")
    membership = db.scalar(select(ClassClusterMember).where(ClassClusterMember.instructional_class_id == instructional_class_id))
    scopes = [and_(PeriodDefinition.scope == "CLASS", PeriodDefinition.target_id == instructional_class_id)]
    if membership:
        scopes.append(and_(PeriodDefinition.scope == "CLUSTER", PeriodDefinition.target_id == membership.cluster_id))
    overrides = db.scalars(select(PeriodDefinition).where(PeriodDefinition.is_active.is_(True), or_(*scopes))).all()
    by_scope_and_slot = {(row.scope, row.slot_code): row for row in overrides}
    resolved = []
    for default in defaults:
        selected = by_scope_and_slot.get(("CLASS", default.slot_code))
        if selected is None and membership:
            selected = by_scope_and_slot.get(("CLUSTER", default.slot_code))
        resolved.append(selected or default)
    return sorted(resolved, key=lambda row: row.display_order)


def validate_period_intervals(db: Session, class_ids: list[int]) -> None:
    for class_id in class_ids:
        periods = resolve_period_rows(db, class_id)
        if any(row.starts_at is None or row.ends_at is None for row in periods):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Period times are incomplete")
        intervals = [(time.fromisoformat(row.starts_at), time.fromisoformat(row.ends_at), row.slot_code) for row in periods]
        intervals.sort()
        for previous, current in zip(intervals, intervals[1:], strict=False):
            if previous[1] > current[0]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Period intervals overlap for class {class_id}: {previous[2]} and {current[2]}",
                )


def affected_class_ids(db: Session, scope: str, target_id: int) -> list[int]:
    if scope == "CLASS":
        return [target_id]
    query = select(InstructionalClass.id).where(InstructionalClass.is_active.is_(True))
    if scope == "CLUSTER":
        query = query.join(ClassClusterMember).where(ClassClusterMember.cluster_id == target_id)
    return list(db.scalars(query).all())
