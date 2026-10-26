import json
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.deps import Claims, DbSession, require_roles
from app.models import TimetablePlacement, TimetableSlot, TimetableVersion, TimetableVersionClass
from app.schemas import TimetableDraftCreate, TimetableLockRequest, TimetablePlacementWrite, TimetableRevisionRequest, TimetableSwapRequest
from app.timetable_lock import lock_timetable_configuration
from app.timetable_planning import (
    assert_current_snapshot,
    assert_stored_plan,
    build_snapshot,
    load_blocks,
    pending_requirements,
    validate_plan,
)

router = APIRouter(
    prefix="/timetable/versions",
    tags=["timetable drafts and amendments"],
    dependencies=[Depends(require_roles("IT Administrator", "Operator", "Executive"))],
)
EDIT_ACCESS = Depends(require_roles("IT Administrator", "Operator"))
APPROVE_ACCESS = Depends(require_roles("IT Administrator"))


def _get(db: DbSession, version_id: int, claims: dict) -> TimetableVersion:
    row = db.get(TimetableVersion, version_id)
    if row is None or (claims["role"] == "Executive" and row.status != "APPROVED"):
        raise HTTPException(status_code=404, detail="Timetable version not found")
    return row


def _summary(row: TimetableVersion) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "academic_year": row.academic_year,
        "week_start": row.week_start,
        "status": row.status,
        "revision": row.revision,
        "created_by": row.created_by,
        "created_at": row.created_at,
        "approved_by": row.approved_by,
        "approved_at": row.approved_at,
    }


def _view(db: DbSession, row: TimetableVersion) -> dict:
    lock_timetable_configuration(db)
    db.refresh(row)
    snapshot = json.loads(row.snapshot_json)
    blocks = load_blocks(db, row.id)
    slots_by_block = {}
    for slot in db.scalars(select(TimetableSlot).where(TimetableSlot.version_id == row.id).order_by(TimetableSlot.id)).all():
        slots_by_block.setdefault(slot.placement_id, []).append(
            {
                "slot_code": slot.slot_code,
                "weekday": slot.weekday,
                "instructional_class_id": slot.instructional_class_id,
                "teacher_id": slot.teacher_id,
                "subject_id": slot.subject_id,
                "starts_at": slot.starts_at.isoformat(timespec="minutes"),
                "ends_at": slot.ends_at.isoformat(timespec="minutes"),
            }
        )
    for block in blocks:
        block["slots"] = sorted(
            slots_by_block.get(block["id"], []), key=lambda slot: {"P1": 1, "P2": 2, "P3": 4, "P4": 5}[slot["slot_code"]]
        )
    return {**_summary(row), "snapshot": snapshot, "placements": blocks, "pending": pending_requirements(snapshot, blocks)}


def _mutation(db: DbSession, version_id: int, expected_revision: int, claims: dict) -> tuple[TimetableVersion, dict, list[dict]]:
    lock_timetable_configuration(db)
    row = _get(db, version_id, claims)
    if row.status != "DRAFT":
        raise HTTPException(status_code=409, detail="Approved timetables are immutable; create a replacement draft")
    if row.revision != expected_revision:
        raise HTTPException(status_code=409, detail="Timetable changed since it was loaded; reload before saving")
    snapshot = assert_current_snapshot(db, row)
    blocks = load_blocks(db, row.id)
    assert_stored_plan(db, row.id, snapshot, blocks)
    return row, snapshot, blocks


def _block(blocks: list[dict], block_id: int, *, require_unlocked: bool = True) -> dict:
    block = next((row for row in blocks if row["id"] == block_id), None)
    if block is None:
        raise HTTPException(status_code=404, detail="Lesson block not found in this timetable")
    if require_unlocked and block["is_locked"]:
        raise HTTPException(status_code=409, detail="Unlock the lesson block before amending it")
    return block


def _finish(
    db: DbSession, version: TimetableVersion, actor_id: int, expected_revision: int, action: str, details: dict, *, approve: bool = False
) -> dict:
    values = {"revision": TimetableVersion.revision + 1}
    if approve:
        values.update(status="APPROVED", approved_by=actor_id, approved_at=datetime.now(UTC))
    changed = db.execute(
        update(TimetableVersion)
        .where(TimetableVersion.id == version.id, TimetableVersion.revision == expected_revision, TimetableVersion.status == "DRAFT")
        .values(**values)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Timetable changed since it was loaded; reload before saving")
    record_event(
        db,
        actor_id,
        action,
        "timetable_version",
        str(version.id),
        {"previous_revision": expected_revision, "revision": expected_revision + 1, **details},
    )
    db.commit()
    return _view(db, version)


def _persist_plan(
    db: DbSession,
    version: TimetableVersion,
    snapshot: dict,
    before: list[dict],
    after: list[dict],
    touched: set[int],
    actor_id: int,
    expected_revision: int,
    action: str,
) -> dict:
    expanded = validate_plan(snapshot, after)
    actual_ids = {}
    try:
        existing_ids = {block["id"] for block in before if block["id"] in touched}
        if existing_ids:
            db.execute(delete(TimetableSlot).where(TimetableSlot.version_id == version.id, TimetableSlot.placement_id.in_(existing_ids)))
            db.flush()
        after_by_id = {block["id"]: block for block in after}
        for block_id in existing_ids - set(after_by_id):
            db.delete(db.get(TimetablePlacement, block_id))
        for block in after:
            if block["id"] not in touched:
                continue
            fields = {key: block[key] for key in ("lesson_requirement_id", "weekday", "start_period", "period_count", "is_locked", "note")}
            if block["id"] < 0:
                row = TimetablePlacement(**fields, version_id=version.id, created_by=actor_id, updated_by=actor_id)
                db.add(row)
            else:
                row = db.get(TimetablePlacement, block["id"])
                for key, value in fields.items():
                    setattr(row, key, value)
                row.updated_by = actor_id
            db.flush()
            actual_ids[block["id"]] = row.id
            db.add_all([TimetableSlot(**slot, placement_id=row.id, version_id=version.id) for slot in expanded[block["id"]]])
            db.flush()
        return _finish(
            db,
            version,
            actor_id,
            expected_revision,
            action,
            {
                "before": [block for block in before if block["id"] in touched],
                "after": [{**block, "id": actual_ids.get(block["id"], block["id"])} for block in after if block["id"] in touched],
            },
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Lesson placement conflicts with stored timetable data") from exc


@router.get("")
def list_versions(
    db: DbSession,
    claims: Claims,
    academic_year: str | None = Query(default=None, max_length=20),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict]:
    query = select(TimetableVersion)
    if claims["role"] == "Executive":
        query = query.where(TimetableVersion.status == "APPROVED")
    if academic_year:
        query = query.where(TimetableVersion.academic_year == academic_year.strip().upper())
    return [_summary(row) for row in db.scalars(query.order_by(TimetableVersion.id.desc()).offset(offset).limit(limit)).all()]


@router.post("", status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_draft(payload: TimetableDraftCreate, db: DbSession, claims: Claims) -> dict:
    lock_timetable_configuration(db)
    snapshot = build_snapshot(db, payload.academic_year, payload.week_start, payload.class_ids)
    row = TimetableVersion(
        name=payload.name,
        academic_year=payload.academic_year,
        week_start=payload.week_start,
        snapshot_json=json.dumps(snapshot, separators=(",", ":"), sort_keys=True),
        created_by=int(claims["sub"]),
        status="DRAFT",
        revision=1,
    )
    try:
        db.add(row)
        db.flush()
        db.add_all([TimetableVersionClass(version_id=row.id, instructional_class_id=class_id) for class_id in payload.class_ids])
        record_event(
            db,
            int(claims["sub"]),
            "timetable.draft.created",
            "timetable_version",
            str(row.id),
            {"class_ids": payload.class_ids, "week_start": payload.week_start.isoformat(), "revision": 1},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Timetable draft conflicts with stored resource data") from exc
    return _view(db, row)


@router.get("/{version_id}")
def get_version(version_id: int, db: DbSession, claims: Claims) -> dict:
    return _view(db, _get(db, version_id, claims))


@router.post("/{version_id}/placements", status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def add_placement(version_id: int, payload: TimetablePlacementWrite, db: DbSession, claims: Claims) -> dict:
    version, snapshot, before = _mutation(db, version_id, payload.expected_revision, claims)
    new = {"id": -1, **payload.model_dump(exclude={"expected_revision"}), "is_locked": False}
    return _persist_plan(
        db, version, snapshot, before, [*before, new], {-1}, int(claims["sub"]), payload.expected_revision, "timetable.lesson.added"
    )


@router.put("/{version_id}/placements/{placement_id}", dependencies=[EDIT_ACCESS])
def amend_placement(version_id: int, placement_id: int, payload: TimetablePlacementWrite, db: DbSession, claims: Claims) -> dict:
    version, snapshot, before = _mutation(db, version_id, payload.expected_revision, claims)
    original = _block(before, placement_id)
    updated = {**original, **payload.model_dump(exclude={"expected_revision"})}
    after = [updated if block["id"] == placement_id else block for block in before]
    return _persist_plan(
        db, version, snapshot, before, after, {placement_id}, int(claims["sub"]), payload.expected_revision, "timetable.lesson.amended"
    )


@router.delete("/{version_id}/placements/{placement_id}", dependencies=[EDIT_ACCESS])
def remove_placement(version_id: int, placement_id: int, db: DbSession, claims: Claims, expected_revision: int = Query(ge=1)) -> dict:
    version, snapshot, before = _mutation(db, version_id, expected_revision, claims)
    _block(before, placement_id)
    return _persist_plan(
        db,
        version,
        snapshot,
        before,
        [block for block in before if block["id"] != placement_id],
        {placement_id},
        int(claims["sub"]),
        expected_revision,
        "timetable.lesson.removed",
    )


@router.patch("/{version_id}/placements/{placement_id}/lock", dependencies=[EDIT_ACCESS])
def lock_placement(version_id: int, placement_id: int, payload: TimetableLockRequest, db: DbSession, claims: Claims) -> dict:
    version, _, blocks = _mutation(db, version_id, payload.expected_revision, claims)
    previous = _block(blocks, placement_id, require_unlocked=False)
    row = db.get(TimetablePlacement, placement_id)
    row.is_locked = payload.is_locked
    row.updated_by = int(claims["sub"])
    try:
        db.flush()
        return _finish(
            db,
            version,
            int(claims["sub"]),
            payload.expected_revision,
            "timetable.lesson.lock_changed",
            {"placement_id": placement_id, "before": previous["is_locked"], "after": payload.is_locked},
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Lesson block lock conflicts with stored timetable data") from exc


@router.post("/{version_id}/swap", dependencies=[EDIT_ACCESS])
def swap_placements(version_id: int, payload: TimetableSwapRequest, db: DbSession, claims: Claims) -> dict:
    version, snapshot, before = _mutation(db, version_id, payload.expected_revision, claims)
    first = _block(before, payload.first_placement_id)
    second = _block(before, payload.second_placement_id)
    changes = {
        first["id"]: {**first, "weekday": second["weekday"], "start_period": second["start_period"]},
        second["id"]: {**second, "weekday": first["weekday"], "start_period": first["start_period"]},
    }
    return _persist_plan(
        db,
        version,
        snapshot,
        before,
        [changes.get(block["id"], block) for block in before],
        set(changes),
        int(claims["sub"]),
        payload.expected_revision,
        "timetable.lessons.swapped",
    )


@router.post("/{version_id}/approve", dependencies=[APPROVE_ACCESS])
def approve_version(version_id: int, payload: TimetableRevisionRequest, db: DbSession, claims: Claims) -> dict:
    version, snapshot, blocks = _mutation(db, version_id, payload.expected_revision, claims)
    validate_plan(snapshot, blocks, require_complete=True)
    try:
        return _finish(
            db,
            version,
            int(claims["sub"]),
            payload.expected_revision,
            "timetable.version.approved",
            {"placement_count": len(blocks)},
            approve=True,
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Timetable approval conflicts with stored data") from exc
