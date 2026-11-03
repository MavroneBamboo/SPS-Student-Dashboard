import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.deps import Claims, DbSession, require_roles
from app.models import SchedulingRule
from app.scheduling_rules import assert_rule_scope_available, resolve_rules, target_resource
from app.schemas import ResolvedRule, RuleCreate, RuleResolutionRequest, RuleResponse, RuleUpdate
from app.student_catalogs import active_academic_year
from app.timetable_lock import lock_timetable_configuration

router = APIRouter(
    prefix="/timetable/rules", tags=["scheduling rules"], dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator"))]
)
EDIT_ACCESS = Depends(require_roles("IT Administrator", "Superuser"))


def _response(row: SchedulingRule) -> RuleResponse:
    try:
        definition = json.loads(row.rule_json)
    except ValueError:
        definition = None
    return RuleResponse(
        id=row.id,
        academic_year=row.academic_year,
        target_type=row.target_type,
        target_id=row.instructional_class_id if row.target_type == "CLASS" else row.cluster_id,
        target_key=row.target_key,
        effective_from=row.effective_from,
        effective_to=row.effective_to,
        rule=definition if isinstance(definition, dict) else None,
        binding_state=row.binding_state,
        version=row.version,
        is_active=row.is_active,
    )


def _get(db: DbSession, rule_id: int) -> SchedulingRule:
    row = db.get(SchedulingRule, rule_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Scheduling rule not found")
    return row


def _values(payload: RuleCreate, target_key: str) -> dict:
    return {
        "academic_year": payload.academic_year,
        "target_type": payload.target_type,
        "target_key": target_key,
        "instructional_class_id": payload.target_id if payload.target_type == "CLASS" else None,
        "cluster_id": payload.target_id if payload.target_type == "CLUSTER" else None,
        "binding_state": "BOUND",
        "effective_from": payload.effective_from,
        "effective_to": payload.effective_to,
        "rule_json": json.dumps(payload.rule.model_dump(), separators=(",", ":"), sort_keys=True),
    }


@router.get("", response_model=list[RuleResponse])
def list_rules(
    db: DbSession,
    claims: Claims,
    academic_year: str | None = Query(default=None, min_length=1, max_length=20),
    include_inactive: bool = False,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[RuleResponse]:
    query = select(SchedulingRule)
    if academic_year:
        query = query.where(func.upper(func.trim(SchedulingRule.academic_year)) == academic_year.strip().upper())
    if not include_inactive:
        query = query.where(SchedulingRule.is_active.is_(True))
    return [_response(row) for row in db.scalars(query.order_by(SchedulingRule.id).offset(offset).limit(limit)).all()]


@router.post("/resolve", response_model=list[ResolvedRule])
def resolve_planning_rules(payload: RuleResolutionRequest, db: DbSession, claims: Claims) -> list[ResolvedRule]:
    return resolve_rules(db, payload)


@router.get("/{rule_id}", response_model=RuleResponse)
def get_rule(rule_id: int, db: DbSession, claims: Claims) -> RuleResponse:
    return _response(_get(db, rule_id))


@router.post("", response_model=RuleResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_rule(payload: RuleCreate, db: DbSession, claims: Claims) -> RuleResponse:
    lock_timetable_configuration(db)
    year = active_academic_year(db, payload.academic_year)
    payload.academic_year = year.code
    if payload.effective_from < year.starts_on or (payload.effective_to and payload.effective_to > year.ends_on):
        raise HTTPException(status_code=422, detail="Scheduling rule dates must fall within the configured academic year")
    target = target_resource(db, payload.target_type, payload.target_id)
    assert_rule_scope_available(
        db, payload.academic_year, payload.target_type, payload.target_id, payload.effective_from, payload.effective_to
    )
    row = SchedulingRule(**_values(payload, target.code), version=1, is_active=True, created_by=int(claims["sub"]))
    try:
        db.add(row)
        db.flush()
        record_event(
            db, int(claims["sub"]), "timetable.rule.created", "scheduling_rule", str(row.id), _response(row).model_dump(mode="json")
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Scheduling rule scope conflicts with existing data") from exc
    db.refresh(row)
    return _response(row)


@router.put("/{rule_id}", response_model=RuleResponse, dependencies=[EDIT_ACCESS])
def update_rule(rule_id: int, payload: RuleUpdate, db: DbSession, claims: Claims) -> RuleResponse:
    lock_timetable_configuration(db)
    row = _get(db, rule_id)
    if payload.is_active:
        year = active_academic_year(db, payload.academic_year)
        if payload.effective_from < year.starts_on or (payload.effective_to and payload.effective_to > year.ends_on):
            raise HTTPException(status_code=422, detail="Scheduling rule dates must fall within the configured academic year")
    target = target_resource(db, payload.target_type, payload.target_id)
    if payload.is_active:
        assert_rule_scope_available(
            db,
            payload.academic_year,
            payload.target_type,
            payload.target_id,
            payload.effective_from,
            payload.effective_to,
            exclude_id=rule_id,
        )
    previous = _response(row).model_dump(mode="json")
    try:
        changed = db.execute(
            update(SchedulingRule)
            .where(SchedulingRule.id == rule_id, SchedulingRule.version == payload.expected_version)
            .values(**_values(payload, target.code), is_active=payload.is_active, version=SchedulingRule.version + 1)
        )
        if changed.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Scheduling rule changed; reload before saving")
        db.refresh(row)
        record_event(
            db,
            int(claims["sub"]),
            "timetable.rule.updated",
            "scheduling_rule",
            str(rule_id),
            {"before": previous, "after": _response(row).model_dump(mode="json")},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Scheduling rule scope conflicts with existing data") from exc
    return _response(row)


@router.delete("/{rule_id}", response_model=RuleResponse, dependencies=[EDIT_ACCESS])
def archive_rule(rule_id: int, db: DbSession, claims: Claims, expected_version: int = Query(ge=1)) -> RuleResponse:
    lock_timetable_configuration(db)
    row = _get(db, rule_id)
    changed = db.execute(
        update(SchedulingRule)
        .where(SchedulingRule.id == rule_id, SchedulingRule.version == expected_version, SchedulingRule.is_active.is_(True))
        .values(is_active=False, version=SchedulingRule.version + 1)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Scheduling rule changed or is already archived")
    record_event(db, int(claims["sub"]), "timetable.rule.archived", "scheduling_rule", str(rule_id), {"previous_version": expected_version})
    db.commit()
    db.refresh(row)
    return _response(row)
