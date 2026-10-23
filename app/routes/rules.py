import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, or_, select

from app.deps import Claims, DbSession, require_roles
from app.models import SchedulingRule
from app.schemas import RuleCreate, RuleResponse

router = APIRouter(prefix="/timetable/rules", tags=["timetable-rules"])


def overlaps(start: date, end: date | None, other_start: date, other_end: date | None) -> bool:
    return (end is None or other_start <= end) and (other_end is None or start <= other_end)


@router.get("", response_model=list[RuleResponse])
def list_rules(db: DbSession, claims: Claims) -> list[RuleResponse]:
    rows = db.scalars(select(SchedulingRule).where(SchedulingRule.is_active.is_(True)).order_by(SchedulingRule.academic_year, SchedulingRule.target_type, SchedulingRule.target_key)).all()
    return [RuleResponse(id=row.id, academic_year=row.academic_year, target_type=row.target_type, target_key=row.target_key, effective_from=row.effective_from, effective_to=row.effective_to, rule=json.loads(row.rule_json), is_active=row.is_active) for row in rows]


@router.post("", response_model=RuleResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator"))])
def create_rule(payload: RuleCreate, db: DbSession, claims: Claims) -> RuleResponse:
    candidates = db.scalars(select(SchedulingRule).where(SchedulingRule.is_active.is_(True), SchedulingRule.academic_year == payload.academic_year)).all()
    for row in candidates:
        same_scope = row.target_type == payload.target_type and row.target_key == payload.target_key
        cluster_overlap = row.target_type == "CLUSTER" and payload.target_type == "CLUSTER" and row.target_key == payload.target_key
        if (same_scope or cluster_overlap) and overlaps(payload.effective_from, payload.effective_to, row.effective_from, row.effective_to):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Duplicate or overlapping scheduling rule")
    row = SchedulingRule(academic_year=payload.academic_year, target_type=payload.target_type, target_key=payload.target_key, effective_from=payload.effective_from, effective_to=payload.effective_to, rule_json=json.dumps(payload.rule, separators=(",", ":"), sort_keys=True), created_by=int(claims["sub"]))
    db.add(row)
    db.commit()
    db.refresh(row)
    return RuleResponse(id=row.id, academic_year=row.academic_year, target_type=row.target_type, target_key=row.target_key, effective_from=row.effective_from, effective_to=row.effective_to, rule=payload.rule, is_active=row.is_active)
