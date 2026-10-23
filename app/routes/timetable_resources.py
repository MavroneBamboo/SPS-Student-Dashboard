import json
from datetime import time as time_value

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.deps import Claims, DbSession, require_roles
from app.models import ClassCluster, ClassClusterMember, InstructionalClass, PeriodDefinition, Subject, Teacher
from app.schemas import (
    ClusterCreate,
    ClusterMemberCreate,
    ClusterResponse,
    InstructionalClassCreate,
    InstructionalClassResponse,
    PeriodCreate,
    PeriodResponse,
    PeriodUpdate,
    SubjectCreate,
    SubjectResponse,
    TeacherCreate,
    TeacherResponse,
)

router = APIRouter(prefix="/timetable", tags=["timetable resource setup"])
READ_ROLES = ("Superuser", "IT Administrator", "Operator", "Executive")
EDIT_ROLES = ("IT Administrator",)
READ_ACCESS = Depends(require_roles(*READ_ROLES))
EDIT_ACCESS = Depends(require_roles(*EDIT_ROLES))


def _normalized_code(value: str) -> str:
    return value.strip().upper()


def _ensure_unique_code(db: DbSession, model: type, code: str) -> None:
    column = model.short_code if model is Teacher else model.code
    if db.scalar(select(model.id).where(func.upper(column) == _normalized_code(code))) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Resource code already exists")


def _commit_or_conflict(db: DbSession, detail: str = "Resource conflicts with existing data") -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from exc


def _flush_or_conflict(db: DbSession, detail: str) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from exc


def _teacher_response(row: Teacher) -> TeacherResponse:
    return TeacherResponse(
        id=row.id,
        short_code=row.short_code,
        full_name=row.full_name,
        is_adjunct=row.is_adjunct,
        availability=json.loads(row.availability_json),
        is_active=row.is_active,
    )


def _resolved_period_rows(db: DbSession, instructional_class_id: int) -> list[PeriodDefinition]:
    defaults = db.scalars(select(PeriodDefinition).where(PeriodDefinition.scope == "DEFAULT", PeriodDefinition.is_active.is_(True))).all()
    if len(defaults) != 5 or {row.slot_code for row in defaults} != {"P1", "P2", "LUNCH", "P3", "P4"}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Default period pattern is incomplete")
    membership = db.scalar(select(ClassClusterMember).where(ClassClusterMember.instructional_class_id == instructional_class_id))
    override_scopes = [and_(PeriodDefinition.scope == "CLASS", PeriodDefinition.target_id == instructional_class_id)]
    if membership:
        override_scopes.append(and_(PeriodDefinition.scope == "CLUSTER", PeriodDefinition.target_id == membership.cluster_id))
    overrides = db.scalars(select(PeriodDefinition).where(PeriodDefinition.is_active.is_(True), or_(*override_scopes))).all()
    by_scope_and_slot = {(row.scope, row.slot_code): row for row in overrides}
    resolved = []
    for default in defaults:
        selected = by_scope_and_slot.get(("CLASS", default.slot_code))
        if selected is None and membership:
            selected = by_scope_and_slot.get(("CLUSTER", default.slot_code))
        resolved.append(selected or default)
    return sorted(resolved, key=lambda row: row.display_order)


def _validate_period_intervals(db: DbSession, class_ids: list[int]) -> None:
    for class_id in class_ids:
        periods = _resolved_period_rows(db, class_id)
        intervals = [(time_value.fromisoformat(row.starts_at), time_value.fromisoformat(row.ends_at), row.slot_code) for row in periods]
        intervals.sort()
        for previous, current in zip(intervals, intervals[1:], strict=False):
            if previous[1] > current[0]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Period intervals overlap for class {class_id}: {previous[2]} and {current[2]}",
                )


def _affected_class_ids(db: DbSession, scope: str, target_id: int) -> list[int]:
    if scope == "CLASS":
        return [target_id]
    query = select(InstructionalClass.id).where(InstructionalClass.is_active.is_(True))
    if scope == "CLUSTER":
        query = query.join(ClassClusterMember).where(ClassClusterMember.cluster_id == target_id)
    return list(db.scalars(query).all())


@router.get("/teachers", response_model=list[TeacherResponse], dependencies=[READ_ACCESS])
def list_teachers(db: DbSession, claims: Claims) -> list[TeacherResponse]:
    return [_teacher_response(row) for row in db.scalars(select(Teacher).order_by(Teacher.short_code)).all()]


@router.post("/teachers", response_model=TeacherResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_teacher(payload: TeacherCreate, db: DbSession, claims: Claims) -> TeacherResponse:
    _ensure_unique_code(db, Teacher, payload.short_code)
    row = Teacher(
        short_code=_normalized_code(payload.short_code),
        full_name=payload.full_name.strip(),
        is_adjunct=payload.is_adjunct,
        availability_json=json.dumps(payload.availability, separators=(",", ":"), sort_keys=True),
        is_active=payload.is_active,
        created_by=int(claims["sub"]),
    )
    db.add(row)
    _flush_or_conflict(db, "Teacher code already exists")
    record_event(db, int(claims["sub"]), "timetable.teacher.created", "teacher", str(row.id), {"short_code": row.short_code})
    _commit_or_conflict(db, "Teacher code already exists")
    db.refresh(row)
    return _teacher_response(row)


@router.get("/subjects", response_model=list[SubjectResponse], dependencies=[READ_ACCESS])
def list_subjects(db: DbSession, claims: Claims) -> list[SubjectResponse]:
    return [SubjectResponse.model_validate(row, from_attributes=True) for row in db.scalars(select(Subject).order_by(Subject.code)).all()]


@router.post("/subjects", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_subject(payload: SubjectCreate, db: DbSession, claims: Claims) -> SubjectResponse:
    _ensure_unique_code(db, Subject, payload.code)
    row = Subject(**payload.model_dump(exclude={"code"}), code=_normalized_code(payload.code), created_by=int(claims["sub"]))
    db.add(row)
    _flush_or_conflict(db, "Subject code already exists")
    record_event(db, int(claims["sub"]), "timetable.subject.created", "subject", str(row.id), {"code": row.code})
    _commit_or_conflict(db, "Subject code already exists")
    db.refresh(row)
    return SubjectResponse.model_validate(row, from_attributes=True)


@router.get("/classes", response_model=list[InstructionalClassResponse], dependencies=[READ_ACCESS])
def list_instructional_classes(db: DbSession, claims: Claims) -> list[InstructionalClassResponse]:
    rows = db.scalars(select(InstructionalClass).order_by(InstructionalClass.reporting_order, InstructionalClass.code)).all()
    return [InstructionalClassResponse.model_validate(row, from_attributes=True) for row in rows]


@router.post("/classes", response_model=InstructionalClassResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_instructional_class(payload: InstructionalClassCreate, db: DbSession, claims: Claims) -> InstructionalClassResponse:
    _ensure_unique_code(db, InstructionalClass, payload.code)
    row = InstructionalClass(**payload.model_dump(exclude={"code"}), code=_normalized_code(payload.code), created_by=int(claims["sub"]))
    db.add(row)
    _flush_or_conflict(db, "Instructional class code already exists")
    record_event(db, int(claims["sub"]), "timetable.class.created", "instructional_class", str(row.id), {"code": row.code})
    _commit_or_conflict(db, "Instructional class code already exists")
    db.refresh(row)
    return InstructionalClassResponse.model_validate(row, from_attributes=True)


def _cluster_response(db: DbSession, row: ClassCluster) -> ClusterResponse:
    class_ids = db.scalars(
        select(ClassClusterMember.instructional_class_id)
        .where(ClassClusterMember.cluster_id == row.id)
        .order_by(ClassClusterMember.instructional_class_id)
    ).all()
    return ClusterResponse(
        id=row.id,
        code=row.code,
        name=row.name,
        description=row.description,
        is_active=row.is_active,
        class_ids=list(class_ids),
    )


@router.get("/clusters", response_model=list[ClusterResponse], dependencies=[READ_ACCESS])
def list_clusters(db: DbSession, claims: Claims) -> list[ClusterResponse]:
    return [_cluster_response(db, row) for row in db.scalars(select(ClassCluster).order_by(ClassCluster.code)).all()]


@router.post("/clusters", response_model=ClusterResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_cluster(payload: ClusterCreate, db: DbSession, claims: Claims) -> ClusterResponse:
    _ensure_unique_code(db, ClassCluster, payload.code)
    row = ClassCluster(**payload.model_dump(exclude={"code"}), code=_normalized_code(payload.code), created_by=int(claims["sub"]))
    db.add(row)
    _flush_or_conflict(db, "Cluster code already exists")
    record_event(db, int(claims["sub"]), "timetable.cluster.created", "class_cluster", str(row.id), {"code": row.code})
    _commit_or_conflict(db, "Cluster code already exists")
    db.refresh(row)
    return _cluster_response(db, row)


@router.post("/clusters/{cluster_id}/classes", status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def add_class_to_cluster(cluster_id: int, payload: ClusterMemberCreate, db: DbSession, claims: Claims) -> dict:
    cluster = db.get(ClassCluster, cluster_id)
    instructional_class = db.get(InstructionalClass, payload.instructional_class_id)
    if cluster is None or instructional_class is None or not cluster.is_active or not instructional_class.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster or instructional class not found")
    if db.scalar(select(ClassClusterMember).where(ClassClusterMember.instructional_class_id == instructional_class.id)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Instructional class already belongs to a cluster")
    membership = ClassClusterMember(cluster_id=cluster.id, instructional_class_id=instructional_class.id, created_by=int(claims["sub"]))
    db.add(membership)
    record_event(
        db,
        int(claims["sub"]),
        "timetable.cluster.class_added",
        "class_cluster",
        str(cluster.id),
        {"instructional_class_id": instructional_class.id},
    )
    _flush_or_conflict(db, "Instructional class already belongs to a cluster")
    try:
        _validate_period_intervals(db, [instructional_class.id])
    except HTTPException:
        db.rollback()
        raise
    _commit_or_conflict(db, "Instructional class already belongs to a cluster")
    return {"cluster_id": cluster.id, "instructional_class_id": instructional_class.id}


def _period_response(row: PeriodDefinition) -> PeriodResponse:
    return PeriodResponse(
        id=row.id,
        scope=row.scope,
        target_id=row.target_id if row.scope != "DEFAULT" else None,
        slot_code=row.slot_code,
        display_order=row.display_order,
        label=row.label,
        starts_at=time_value.fromisoformat(row.starts_at) if row.starts_at else None,
        ends_at=time_value.fromisoformat(row.ends_at) if row.ends_at else None,
        is_schedulable=row.is_schedulable,
        is_active=row.is_active,
    )


@router.get("/periods", response_model=list[PeriodResponse], dependencies=[READ_ACCESS])
def list_period_definitions(db: DbSession, claims: Claims) -> list[PeriodResponse]:
    rows = db.scalars(select(PeriodDefinition).where(PeriodDefinition.is_active.is_(True)).order_by(PeriodDefinition.display_order)).all()
    return [_period_response(row) for row in rows]


@router.post("/periods", response_model=PeriodResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_period_definition(payload: PeriodCreate, db: DbSession, claims: Claims) -> PeriodResponse:
    target_id = payload.target_id or 0
    target_class = db.get(InstructionalClass, target_id) if payload.scope == "CLASS" else None
    target_cluster = db.get(ClassCluster, target_id) if payload.scope == "CLUSTER" else None
    if payload.scope == "CLASS" and (target_class is None or not target_class.is_active):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instructional class not found")
    if payload.scope == "CLUSTER" and (target_cluster is None or not target_cluster.is_active):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Class cluster not found")
    row = PeriodDefinition(
        scope=payload.scope,
        target_id=target_id,
        slot_code=payload.slot_code,
        display_order={"P1": 1, "P2": 2, "LUNCH": 3, "P3": 4, "P4": 5}[payload.slot_code],
        label="Lunch" if payload.slot_code == "LUNCH" else payload.label.strip(),
        starts_at=payload.starts_at.isoformat(timespec="minutes") if payload.starts_at else None,
        ends_at=payload.ends_at.isoformat(timespec="minutes") if payload.ends_at else None,
        is_schedulable=payload.slot_code != "LUNCH",
        is_active=True,
        created_by=int(claims["sub"]),
    )
    db.add(row)
    _flush_or_conflict(db, "A period override for this scope and slot already exists")
    try:
        _validate_period_intervals(db, _affected_class_ids(db, payload.scope, target_id))
    except HTTPException:
        db.rollback()
        raise
    record_event(
        db,
        int(claims["sub"]),
        "timetable.period.created",
        "period_definition",
        str(row.id),
        {"scope": row.scope, "target_id": row.target_id, "slot_code": row.slot_code},
    )
    _commit_or_conflict(db, "A period override for this scope and slot already exists")
    db.refresh(row)
    return _period_response(row)


@router.patch("/periods/{period_id}", response_model=PeriodResponse, dependencies=[EDIT_ACCESS])
def update_period_definition(period_id: int, payload: PeriodUpdate, db: DbSession, claims: Claims) -> PeriodResponse:
    row = db.get(PeriodDefinition, period_id)
    if row is None or not row.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Period definition not found")
    changes = payload.model_dump(exclude_unset=True)
    if row.slot_code == "LUNCH" and changes.get("label", "Lunch").strip().upper() != "LUNCH":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Lunch must remain labelled Lunch")
    starts_at = changes.get("starts_at", time_value.fromisoformat(row.starts_at) if row.starts_at else None)
    ends_at = changes.get("ends_at", time_value.fromisoformat(row.ends_at) if row.ends_at else None)
    if starts_at is None or ends_at is None or ends_at <= starts_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Period start and end times must form a valid interval",
        )
    previous = {"label": row.label, "starts_at": row.starts_at, "ends_at": row.ends_at}
    for field, value in changes.items():
        setattr(row, field, value.strip() if field == "label" else value.isoformat(timespec="minutes"))
    try:
        db.flush()
        _validate_period_intervals(db, _affected_class_ids(db, row.scope, row.target_id))
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Period update conflicts with existing data") from exc
    record_event(
        db,
        int(claims["sub"]),
        "timetable.period.updated",
        "period_definition",
        str(row.id),
        {"before": previous, "after": {"label": row.label, "starts_at": row.starts_at, "ends_at": row.ends_at}},
    )
    _commit_or_conflict(db, "Period update conflicts with existing data")
    db.refresh(row)
    return _period_response(row)


@router.get("/classes/{class_id}/periods", response_model=list[PeriodResponse], dependencies=[READ_ACCESS])
def resolve_class_periods(class_id: int, db: DbSession, claims: Claims) -> list[PeriodResponse]:
    instructional_class = db.get(InstructionalClass, class_id)
    if instructional_class is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instructional class not found")
    try:
        _validate_period_intervals(db, [class_id])
    except HTTPException as exc:
        raise exc
    return [_period_response(row) for row in _resolved_period_rows(db, class_id)]
