import hashlib
import json
from datetime import time as time_value

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.deps import Claims, DbSession, require_roles
from app.lesson_validation import validate_existing_class_lessons, validate_lesson_resources
from app.models import (
    AttendanceClassMapping,
    ClassCluster,
    ClassClusterMember,
    InstructionalClass,
    LessonRequirement,
    PeriodDefinition,
    SchedulingRule,
    StudentClassMapping,
    Subject,
    Teacher,
    TeacherGroupMember,
    TimetableFixedEvent,
)
from app.scheduling_rules import assert_membership_rules_compatible
from app.schemas import (
    ClusterCreate,
    ClusterMemberCreate,
    ClusterResponse,
    InstructionalClassCreate,
    InstructionalClassResponse,
    InstructionalClassUpdate,
    LessonRequirementCreate,
    PeriodCreate,
    PeriodResponse,
    PeriodUpdate,
    SubjectCreate,
    SubjectResponse,
    SubjectUpdate,
    TeacherCreate,
    TeacherGroupCreate,
    TeacherResponse,
    TeacherUpdate,
)
from app.timetable_lock import lock_timetable_configuration
from app.timetable_periods import affected_class_ids as _affected_class_ids
from app.timetable_periods import resolve_period_rows as _resolved_period_rows
from app.timetable_periods import validate_period_intervals as _validate_period_intervals

router = APIRouter(prefix="/timetable", tags=["timetable resource setup"])
READ_ROLES = ("Superuser", "IT Administrator", "Operator", "Executive")
EDIT_ROLES = ("IT Administrator", "Superuser")
READ_ACCESS = Depends(require_roles(*READ_ROLES))
EDIT_ACCESS = Depends(require_roles(*EDIT_ROLES))


def _normalized_code(value: str) -> str:
    return value.strip().upper()


def _ensure_unique_code(db: DbSession, model: type, code: str, *, exclude_id: int | None = None) -> None:
    column = model.short_code if model is Teacher else model.code
    query = select(model.id).where(func.upper(column) == _normalized_code(code))
    if exclude_id is not None:
        query = query.where(model.id != exclude_id)
    if db.scalar(query) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Resource code already exists")


def _revision(kind: str, values: dict) -> str:
    encoded = json.dumps({"kind": kind, **values}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _event_revision(
    db: DbSession, actor_id: int, action: str, entity: str, row_id: int, before: str, after: str, fields: list[str]
) -> None:
    record_event(
        db,
        actor_id,
        action,
        entity,
        str(row_id),
        {"before_revision": before, "after_revision": after, "changed_fields": sorted(fields)},
    )


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


def _teacher_response(db: DbSession, row: Teacher) -> TeacherResponse:
    member_ids = db.scalars(
        select(TeacherGroupMember.member_teacher_id)
        .where(TeacherGroupMember.group_teacher_id == row.id)
        .order_by(TeacherGroupMember.member_teacher_id)
    ).all()
    availability = json.loads(row.availability_json)
    values = {
        "id": row.id,
        "short_code": row.short_code,
        "full_name": row.full_name,
        "is_adjunct": row.is_adjunct,
        "availability": availability,
        "is_active": row.is_active,
        "is_composite": row.is_composite,
        "member_ids": member_ids,
    }
    return TeacherResponse(
        id=row.id,
        short_code=row.short_code,
        full_name=row.full_name,
        is_adjunct=row.is_adjunct,
        availability=availability,
        is_active=row.is_active,
        is_composite=row.is_composite,
        member_ids=member_ids,
        revision=_revision("teacher", values),
    )


def _subject_response(row: Subject) -> SubjectResponse:
    values = {"id": row.id, "code": row.code, "name": row.name, "description": row.description, "is_active": row.is_active}
    return SubjectResponse(**values, revision=_revision("subject", values))


def _class_response(row: InstructionalClass) -> InstructionalClassResponse:
    values = {
        "id": row.id,
        "code": row.code,
        "name": row.name,
        "description": row.description,
        "reporting_order": row.reporting_order,
        "is_active": row.is_active,
    }
    return InstructionalClassResponse(**values, revision=_revision("instructional_class", values))


def _event_references(db: DbSession, audience_type: str, target_id: int) -> bool:
    for event in db.scalars(
        select(TimetableFixedEvent).where(TimetableFixedEvent.is_active.is_(True), TimetableFixedEvent.audience_type == audience_type)
    ).all():
        if event.target_mode == "SELECTED" and target_id in json.loads(event.target_ids_json):
            return True
    return False


def _ensure_teacher_can_deactivate(db: DbSession, teacher: Teacher) -> None:
    active_requirement = db.scalar(
        select(LessonRequirement.id).where(LessonRequirement.is_active.is_(True), LessonRequirement.teacher_id == teacher.id)
    )
    active_group = db.scalar(
        select(TeacherGroupMember.id)
        .join(Teacher, Teacher.id == TeacherGroupMember.group_teacher_id)
        .where(TeacherGroupMember.member_teacher_id == teacher.id, Teacher.is_active.is_(True), Teacher.is_composite.is_(True))
    )
    if active_requirement or active_group or _event_references(db, "TEACHER", teacher.id):
        raise HTTPException(
            status_code=409, detail="Archive dependent lessons and resolve active teacher groups or events before deactivation"
        )


def _ensure_subject_can_deactivate(db: DbSession, subject: Subject) -> None:
    if db.scalar(select(LessonRequirement.id).where(LessonRequirement.is_active.is_(True), LessonRequirement.subject_id == subject.id)):
        raise HTTPException(status_code=409, detail="Archive dependent lesson requirements before deactivating this subject")


def _ensure_class_can_deactivate(db: DbSession, instructional_class: InstructionalClass) -> None:
    checks = (
        db.scalar(
            select(LessonRequirement.id).where(
                LessonRequirement.is_active.is_(True), LessonRequirement.instructional_class_id == instructional_class.id
            )
        ),
        db.scalar(
            select(StudentClassMapping.id).where(
                StudentClassMapping.is_active.is_(True), StudentClassMapping.instructional_class_id == instructional_class.id
            )
        ),
        db.scalar(
            select(AttendanceClassMapping.id).where(
                AttendanceClassMapping.is_active.is_(True), AttendanceClassMapping.instructional_class_id == instructional_class.id
            )
        ),
        db.scalar(
            select(SchedulingRule.id).where(
                SchedulingRule.is_active.is_(True),
                SchedulingRule.target_type == "CLASS",
                SchedulingRule.instructional_class_id == instructional_class.id,
            )
        ),
        db.scalar(
            select(PeriodDefinition.id).where(
                PeriodDefinition.is_active.is_(True),
                PeriodDefinition.scope == "CLASS",
                PeriodDefinition.target_id == instructional_class.id,
            )
        ),
    )
    if any(checks) or _event_references(db, "CLASS", instructional_class.id):
        raise HTTPException(
            status_code=409,
            detail="Resolve dependent lessons, mappings, rules, period overrides or fixed events before deactivating this class",
        )


@router.get("/teachers", response_model=list[TeacherResponse], dependencies=[READ_ACCESS])
def list_teachers(db: DbSession, claims: Claims) -> list[TeacherResponse]:
    return [_teacher_response(db, row) for row in db.scalars(select(Teacher).order_by(Teacher.short_code)).all()]


@router.post("/teachers", response_model=TeacherResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_teacher(payload: TeacherCreate, db: DbSession, claims: Claims) -> TeacherResponse:
    lock_timetable_configuration(db)
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
    return _teacher_response(db, row)


def _refresh_composite_availability(db: DbSession, member_id: int) -> list[Teacher]:
    groups = db.scalars(
        select(Teacher)
        .join(TeacherGroupMember, TeacherGroupMember.group_teacher_id == Teacher.id)
        .where(TeacherGroupMember.member_teacher_id == member_id, Teacher.is_active.is_(True), Teacher.is_composite.is_(True))
    ).all()
    for group in groups:
        member_ids = db.scalars(select(TeacherGroupMember.member_teacher_id).where(TeacherGroupMember.group_teacher_id == group.id)).all()
        members = [db.get(Teacher, current_id) for current_id in member_ids]
        if len(members) < 2 or any(member is None or not member.is_active or member.is_composite for member in members):
            raise HTTPException(status_code=409, detail="The teacher change would invalidate an active composite group")
        member_availability = [json.loads(member.availability_json) for member in members]
        common = {
            day: sorted(set.intersection(*(set(availability[day]) for availability in member_availability)))
            for day in ("MON", "TUE", "WED", "THU", "FRI")
        }
        group.availability_json = json.dumps(common, separators=(",", ":"), sort_keys=True)
    return groups


@router.patch("/teachers/{teacher_id}", response_model=TeacherResponse, dependencies=[EDIT_ACCESS])
def update_teacher(teacher_id: int, payload: TeacherUpdate, db: DbSession, claims: Claims) -> TeacherResponse:
    lock_timetable_configuration(db)
    row = db.get(Teacher, teacher_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Teacher profile not found")
    before = _teacher_response(db, row)
    if payload.expected_revision != before.revision:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Teacher profile changed; reload it before saving")
    changes = payload.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    group_revisions = {}
    if "availability" in changes and not row.is_composite:
        groups_before = db.scalars(
            select(Teacher)
            .join(TeacherGroupMember, TeacherGroupMember.group_teacher_id == Teacher.id)
            .where(TeacherGroupMember.member_teacher_id == row.id, Teacher.is_active.is_(True), Teacher.is_composite.is_(True))
        ).all()
        group_revisions = {group.id: _teacher_response(db, group).revision for group in groups_before}
    if row.is_composite and {"availability", "is_adjunct"} & changes.keys():
        raise HTTPException(status_code=422, detail="Composite teacher availability and type are derived from group members")
    if changes.get("is_active") is False and row.is_active:
        _ensure_teacher_can_deactivate(db, row)
    if "short_code" in changes:
        _ensure_unique_code(db, Teacher, changes["short_code"], exclude_id=row.id)
        changes["short_code"] = _normalized_code(changes["short_code"])
    if "availability" in changes:
        try:
            TeacherCreate(
                short_code=changes.get("short_code", row.short_code),
                full_name=changes.get("full_name", row.full_name),
                is_adjunct=changes.get("is_adjunct", row.is_adjunct),
                availability=changes["availability"],
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Teacher availability is invalid") from exc
        changes["availability_json"] = json.dumps(changes.pop("availability"), separators=(",", ":"), sort_keys=True)
    for field, value in changes.items():
        setattr(row, field, value)
    affected = [row]
    if "availability_json" in changes and not row.is_composite:
        affected.extend(_refresh_composite_availability(db, row.id))
        for requirement in db.scalars(
            select(LessonRequirement).where(
                LessonRequirement.is_active.is_(True),
                LessonRequirement.teacher_id.in_([teacher.id for teacher in affected]),
            )
        ).all():
            try:
                validate_lesson_resources(db, LessonRequirementCreate.model_validate(requirement, from_attributes=True))
            except HTTPException as exc:
                db.rollback()
                raise HTTPException(
                    status_code=409,
                    detail={"message": "Teacher availability change would invalidate an active lesson requirement", "reason": exc.detail},
                ) from exc
    try:
        _flush_or_conflict(db, "Teacher update conflicts with existing data")
        after = _teacher_response(db, row)
        for group in affected[1:]:
            group_after = _teacher_response(db, group)
            previous_revision = group_revisions.get(group.id)
            if previous_revision and previous_revision != group_after.revision:
                _event_revision(
                    db,
                    int(claims["sub"]),
                    "timetable.teacher_group.availability_recomputed",
                    "teacher_group",
                    group.id,
                    previous_revision,
                    group_after.revision,
                    ["availability"],
                )
        _event_revision(
            db,
            int(claims["sub"]),
            "timetable.teacher.updated",
            "teacher",
            row.id,
            before.revision,
            after.revision,
            ["availability" if field == "availability_json" else field for field in changes],
        )
        _commit_or_conflict(db, "Teacher update conflicts with existing data")
    except HTTPException:
        db.rollback()
        raise
    db.refresh(row)
    return _teacher_response(db, row)


@router.post("/teacher-groups", response_model=TeacherResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_teacher_group(payload: TeacherGroupCreate, db: DbSession, claims: Claims) -> TeacherResponse:
    lock_timetable_configuration(db)
    _ensure_unique_code(db, Teacher, payload.short_code)
    members = db.scalars(select(Teacher).where(Teacher.id.in_(payload.member_ids)).order_by(Teacher.id)).all()
    if len(members) != len(payload.member_ids) or any(not member.is_active or member.is_composite for member in members):
        raise HTTPException(status_code=422, detail="Teacher groups can contain only distinct active individual teachers")
    try:
        member_availability = [
            TeacherCreate(
                short_code=member.short_code,
                full_name=member.full_name,
                availability=json.loads(member.availability_json),
            ).availability
            for member in members
        ]
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="A teacher group member has invalid availability that IT must correct") from exc
    common_availability = {
        day: sorted(set.intersection(*(set(availability[day]) for availability in member_availability)))
        for day in ("MON", "TUE", "WED", "THU", "FRI")
    }
    row = Teacher(
        short_code=_normalized_code(payload.short_code),
        full_name=payload.full_name.strip(),
        is_adjunct=False,
        is_composite=True,
        availability_json=json.dumps(common_availability, separators=(",", ":"), sort_keys=True),
        is_active=True,
        created_by=int(claims["sub"]),
    )
    db.add(row)
    _flush_or_conflict(db, "Teacher group code already exists")
    for member in members:
        db.add(TeacherGroupMember(group_teacher_id=row.id, member_teacher_id=member.id, created_by=int(claims["sub"])))
    record_event(
        db,
        int(claims["sub"]),
        "timetable.teacher_group.created",
        "teacher_group",
        str(row.id),
        {"short_code": row.short_code, "member_ids": sorted(payload.member_ids)},
    )
    _commit_or_conflict(db, "Teacher group could not be created")
    db.refresh(row)
    return _teacher_response(db, row)


@router.get("/subjects", response_model=list[SubjectResponse], dependencies=[READ_ACCESS])
def list_subjects(db: DbSession, claims: Claims) -> list[SubjectResponse]:
    return [_subject_response(row) for row in db.scalars(select(Subject).order_by(Subject.code)).all()]


@router.post("/subjects", response_model=SubjectResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_subject(payload: SubjectCreate, db: DbSession, claims: Claims) -> SubjectResponse:
    lock_timetable_configuration(db)
    _ensure_unique_code(db, Subject, payload.code)
    row = Subject(**payload.model_dump(exclude={"code"}), code=_normalized_code(payload.code), created_by=int(claims["sub"]))
    db.add(row)
    _flush_or_conflict(db, "Subject code already exists")
    record_event(db, int(claims["sub"]), "timetable.subject.created", "subject", str(row.id), {"code": row.code})
    _commit_or_conflict(db, "Subject code already exists")
    db.refresh(row)
    return _subject_response(row)


@router.patch("/subjects/{subject_id}", response_model=SubjectResponse, dependencies=[EDIT_ACCESS])
def update_subject(subject_id: int, payload: SubjectUpdate, db: DbSession, claims: Claims) -> SubjectResponse:
    lock_timetable_configuration(db)
    row = db.get(Subject, subject_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Subject not found")
    before = _subject_response(row)
    if payload.expected_revision != before.revision:
        raise HTTPException(status_code=409, detail="Subject changed; reload it before saving")
    changes = payload.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    if changes.get("is_active") is False and row.is_active:
        _ensure_subject_can_deactivate(db, row)
    if "code" in changes:
        _ensure_unique_code(db, Subject, changes["code"], exclude_id=row.id)
        changes["code"] = _normalized_code(changes["code"])
    for field, value in changes.items():
        setattr(row, field, value)
    _flush_or_conflict(db, "Subject update conflicts with existing data")
    after = _subject_response(row)
    _event_revision(db, int(claims["sub"]), "timetable.subject.updated", "subject", row.id, before.revision, after.revision, list(changes))
    _commit_or_conflict(db, "Subject update conflicts with existing data")
    db.refresh(row)
    return _subject_response(row)


@router.get("/classes", response_model=list[InstructionalClassResponse], dependencies=[READ_ACCESS])
def list_instructional_classes(db: DbSession, claims: Claims) -> list[InstructionalClassResponse]:
    rows = db.scalars(select(InstructionalClass).order_by(InstructionalClass.reporting_order, InstructionalClass.code)).all()
    return [_class_response(row) for row in rows]


@router.post("/classes", response_model=InstructionalClassResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_instructional_class(payload: InstructionalClassCreate, db: DbSession, claims: Claims) -> InstructionalClassResponse:
    lock_timetable_configuration(db)
    _ensure_unique_code(db, InstructionalClass, payload.code)
    row = InstructionalClass(**payload.model_dump(exclude={"code"}), code=_normalized_code(payload.code), created_by=int(claims["sub"]))
    db.add(row)
    _flush_or_conflict(db, "Instructional class code already exists")
    record_event(db, int(claims["sub"]), "timetable.class.created", "instructional_class", str(row.id), {"code": row.code})
    _commit_or_conflict(db, "Instructional class code already exists")
    db.refresh(row)
    return _class_response(row)


@router.patch("/classes/{class_id}", response_model=InstructionalClassResponse, dependencies=[EDIT_ACCESS])
def update_instructional_class(
    class_id: int, payload: InstructionalClassUpdate, db: DbSession, claims: Claims
) -> InstructionalClassResponse:
    lock_timetable_configuration(db)
    row = db.get(InstructionalClass, class_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Instructional class not found")
    before = _class_response(row)
    if payload.expected_revision != before.revision:
        raise HTTPException(status_code=409, detail="Instructional class changed; reload it before saving")
    changes = payload.model_dump(exclude={"expected_revision"}, exclude_unset=True)
    if changes.get("is_active") is False and row.is_active:
        _ensure_class_can_deactivate(db, row)
    if "code" in changes:
        _ensure_unique_code(db, InstructionalClass, changes["code"], exclude_id=row.id)
        changes["code"] = _normalized_code(changes["code"])
    for field, value in changes.items():
        setattr(row, field, value)
    _flush_or_conflict(db, "Instructional class update conflicts with existing data")
    after = _class_response(row)
    _event_revision(
        db,
        int(claims["sub"]),
        "timetable.class.updated",
        "instructional_class",
        row.id,
        before.revision,
        after.revision,
        list(changes),
    )
    _commit_or_conflict(db, "Instructional class update conflicts with existing data")
    db.refresh(row)
    return _class_response(row)


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
    lock_timetable_configuration(db)
    cluster = db.get(ClassCluster, cluster_id)
    instructional_class = db.get(InstructionalClass, payload.instructional_class_id)
    if cluster is None or instructional_class is None or not cluster.is_active or not instructional_class.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cluster or instructional class not found")
    if db.scalar(select(ClassClusterMember).where(ClassClusterMember.instructional_class_id == instructional_class.id)):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Instructional class already belongs to a cluster")
    assert_membership_rules_compatible(db, instructional_class.id, cluster.id)
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
        validate_existing_class_lessons(db, [instructional_class.id])
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
    lock_timetable_configuration(db)
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
        class_ids = _affected_class_ids(db, payload.scope, target_id)
        _validate_period_intervals(db, class_ids)
        validate_existing_class_lessons(db, class_ids)
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
    lock_timetable_configuration(db)
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
        class_ids = _affected_class_ids(db, row.scope, row.target_id)
        _validate_period_intervals(db, class_ids)
        validate_existing_class_lessons(db, class_ids)
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
