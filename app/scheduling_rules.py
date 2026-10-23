import json
from datetime import date

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import ClassCluster, ClassClusterMember, InstructionalClass, SchedulingRule
from app.schemas import ResolvedRule, RuleDefinition, RuleResolutionRequest
from app.timetable_lock import lock_timetable_configuration


def overlaps(start: date, end: date | None, other_start: date, other_end: date | None) -> bool:
    return (end is None or other_start <= end) and (other_end is None or start <= other_end)


def target_resource(db: Session, target_type: str, target_id: int):
    target = db.get(InstructionalClass if target_type == "CLASS" else ClassCluster, target_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=422, detail="Rule target must be an existing active class or cluster")
    return target


def _covered_classes(db: Session, target_type: str, target_id: int) -> set[int]:
    if target_type == "CLASS":
        return {target_id}
    return set(db.scalars(select(ClassClusterMember.instructional_class_id).where(ClassClusterMember.cluster_id == target_id)).all())


def assert_rule_scope_available(
    db: Session,
    academic_year: str,
    target_type: str,
    target_id: int,
    effective_from: date,
    effective_to: date | None,
    exclude_id: int | None = None,
) -> None:
    classes = _covered_classes(db, target_type, target_id)
    candidates = db.scalars(
        select(SchedulingRule).where(
            SchedulingRule.is_active.is_(True),
            SchedulingRule.binding_state == "BOUND",
            func.upper(func.trim(SchedulingRule.academic_year)) == academic_year.strip().upper(),
        )
    ).all()
    for other in candidates:
        if other.id == exclude_id or not overlaps(effective_from, effective_to, other.effective_from, other.effective_to):
            continue
        other_target_id = other.instructional_class_id if other.target_type == "CLASS" else other.cluster_id
        if (other.target_type == target_type and other_target_id == target_id) or classes & _covered_classes(
            db, other.target_type, other_target_id
        ):
            raise HTTPException(
                status_code=409, detail={"message": "Duplicate or overlapping scheduling rule", "conflicting_rule_id": other.id}
            )


def assert_membership_rules_compatible(db: Session, instructional_class_id: int, cluster_id: int) -> None:
    class_rules = db.scalars(
        select(SchedulingRule).where(
            SchedulingRule.is_active.is_(True),
            SchedulingRule.binding_state == "BOUND",
            SchedulingRule.instructional_class_id == instructional_class_id,
        )
    ).all()
    cluster_rules = db.scalars(
        select(SchedulingRule).where(
            SchedulingRule.is_active.is_(True), SchedulingRule.binding_state == "BOUND", SchedulingRule.cluster_id == cluster_id
        )
    ).all()
    for class_rule in class_rules:
        for cluster_rule in cluster_rules:
            if class_rule.academic_year.strip().upper() == cluster_rule.academic_year.strip().upper() and overlaps(
                class_rule.effective_from, class_rule.effective_to, cluster_rule.effective_from, cluster_rule.effective_to
            ):
                raise HTTPException(status_code=409, detail="Cluster membership would create overlapping class/cluster scheduling rules")


def resolve_rules(db: Session, request: RuleResolutionRequest) -> list[ResolvedRule]:
    lock_timetable_configuration(db)
    classes = {row.id: row for row in db.scalars(select(InstructionalClass).where(InstructionalClass.id.in_(request.class_ids))).all()}
    if any(class_id not in classes or not classes[class_id].is_active for class_id in request.class_ids):
        raise HTTPException(status_code=422, detail="Every planned class must exist and be active")
    candidates = db.scalars(
        select(SchedulingRule).where(
            SchedulingRule.is_active.is_(True),
            func.upper(func.trim(SchedulingRule.academic_year)) == request.academic_year,
            or_(
                and_(
                    SchedulingRule.effective_from <= request.on_date,
                    or_(SchedulingRule.effective_to.is_(None), SchedulingRule.effective_to >= request.on_date),
                ),
                and_(SchedulingRule.binding_state == "UNRESOLVED", SchedulingRule.effective_to < SchedulingRule.effective_from),
            ),
        )
    ).all()
    unresolved = [row.id for row in candidates if row.binding_state != "BOUND"]
    if unresolved:
        raise HTTPException(
            status_code=409, detail={"message": "Legacy rule targets need explicit binding or archival", "rule_ids": unresolved}
        )
    memberships = dict(
        db.execute(
            select(ClassClusterMember.instructional_class_id, ClassClusterMember.cluster_id).where(
                ClassClusterMember.instructional_class_id.in_(request.class_ids)
            )
        ).all()
    )
    results = []
    errors = []
    for class_id in request.class_ids:
        matches = [
            row
            for row in candidates
            if row.instructional_class_id == class_id or (row.cluster_id is not None and row.cluster_id == memberships.get(class_id))
        ]
        if len(matches) != 1:
            errors.append(
                {
                    "instructional_class_id": class_id,
                    "reason": "missing" if not matches else "ambiguous",
                    "rule_ids": [row.id for row in matches],
                }
            )
            continue
        row = matches[0]
        if row.cluster_id is not None:
            cluster = db.get(ClassCluster, row.cluster_id)
            if cluster is None or not cluster.is_active:
                errors.append({"instructional_class_id": class_id, "reason": "inactive cluster", "rule_ids": [row.id]})
                continue
        try:
            definition = RuleDefinition.model_validate(json.loads(row.rule_json))
        except ValueError as exc:
            raise HTTPException(
                status_code=409, detail={"message": "Scheduling rule definition needs correction", "rule_id": row.id}
            ) from exc
        results.append(
            ResolvedRule(
                instructional_class_id=class_id,
                rule_id=row.id,
                version=row.version,
                target_type=row.target_type,
                target_id=row.instructional_class_id if row.target_type == "CLASS" else row.cluster_id,
                rule=definition,
            )
        )
    if errors:
        raise HTTPException(
            status_code=409, detail={"message": "Every planned class must resolve exactly one scheduling rule", "classes": errors}
        )
    return results
