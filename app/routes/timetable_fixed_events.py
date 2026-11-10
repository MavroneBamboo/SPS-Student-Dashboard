import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.deps import Claims, DbSession, require_roles
from app.models import InstructionalClass, Teacher, TimetableFixedEvent
from app.schemas import TimetableFixedEventCreate, TimetableFixedEventResponse, TimetableFixedEventUpdate
from app.timetable_lock import lock_timetable_configuration

router = APIRouter(prefix="/timetable/fixed-events", tags=["timetable fixed events"])
READ_ACCESS = Depends(require_roles("Superuser", "IT Administrator", "Operator", "Executive"))
EDIT_ACCESS = Depends(require_roles("Superuser", "IT Administrator"))


def _payload(row: TimetableFixedEvent) -> dict:
    return {
        "id": row.id,
        "academic_year": row.academic_year,
        "label": row.label,
        "audience_type": row.audience_type,
        "target_mode": row.target_mode,
        "target_ids": json.loads(row.target_ids_json),
        "slots": json.loads(row.slots_json),
        "is_active": row.is_active,
        "version": row.version,
    }


def _validate_targets(db: DbSession, payload: TimetableFixedEventCreate) -> None:
    if payload.target_mode == "ALL":
        return
    model = InstructionalClass if payload.audience_type == "CLASS" else Teacher
    active_ids = set(db.scalars(select(model.id).where(model.id.in_(payload.target_ids), model.is_active.is_(True))).all())
    if active_ids != set(payload.target_ids):
        raise HTTPException(status_code=422, detail="Every selected fixed-event target must exist and be active")


def _slots(payload: TimetableFixedEventCreate) -> set[tuple[str, str]]:
    return {(slot.weekday, slot.slot_code) for slot in payload.slots}


def _assert_no_overlap(db: DbSession, payload: TimetableFixedEventCreate, *, exclude_id: int | None = None) -> None:
    if not payload.is_active:
        return
    stmt = select(TimetableFixedEvent).where(
        TimetableFixedEvent.is_active.is_(True),
        func.upper(func.trim(TimetableFixedEvent.academic_year)) == payload.academic_year.strip().upper(),
        TimetableFixedEvent.audience_type == payload.audience_type,
    )
    if exclude_id is not None:
        stmt = stmt.where(TimetableFixedEvent.id != exclude_id)
    desired_slots = _slots(payload)
    for existing in db.scalars(stmt).all():
        existing_slots = {(slot["weekday"], slot["slot_code"]) for slot in json.loads(existing.slots_json)}
        if not desired_slots.intersection(existing_slots):
            continue
        if payload.target_mode == "ALL" or existing.target_mode == "ALL":
            raise HTTPException(status_code=409, detail=f"Fixed event overlaps {existing.label} for the same audience")
        existing_targets = set(json.loads(existing.target_ids_json))
        if existing_targets.intersection(payload.target_ids):
            raise HTTPException(status_code=409, detail=f"Fixed event overlaps {existing.label} for a shared target")


def _encode(payload: TimetableFixedEventCreate) -> tuple[str, str, str, str]:
    return (
        payload.academic_year.strip().upper(),
        payload.label.strip(),
        json.dumps(sorted(payload.target_ids) if payload.target_mode == "SELECTED" else [], separators=(",", ":")),
        json.dumps(
            sorted((slot.model_dump() for slot in payload.slots), key=lambda slot: (slot["weekday"], slot["slot_code"])),
            separators=(",", ":"),
        ),
    )


@router.get("", response_model=list[TimetableFixedEventResponse], dependencies=[READ_ACCESS])
def list_fixed_events(db: DbSession, claims: Claims) -> list[TimetableFixedEventResponse]:
    rows = db.scalars(
        select(TimetableFixedEvent).order_by(TimetableFixedEvent.academic_year, TimetableFixedEvent.label, TimetableFixedEvent.id)
    ).all()
    return [TimetableFixedEventResponse.model_validate(_payload(row)) for row in rows]


@router.post("", response_model=TimetableFixedEventResponse, status_code=status.HTTP_201_CREATED, dependencies=[EDIT_ACCESS])
def create_fixed_event(payload: TimetableFixedEventCreate, db: DbSession, claims: Claims) -> TimetableFixedEventResponse:
    lock_timetable_configuration(db)
    _validate_targets(db, payload)
    _assert_no_overlap(db, payload)
    academic_year, label, target_ids, slots = _encode(payload)
    actor = int(claims["sub"])
    row = TimetableFixedEvent(
        academic_year=academic_year,
        label=label,
        audience_type=payload.audience_type,
        target_mode=payload.target_mode,
        target_ids_json=target_ids,
        slots_json=slots,
        is_active=payload.is_active,
        created_by=actor,
        updated_by=actor,
    )
    db.add(row)
    try:
        db.flush()
        record_event(db, actor, "timetable.fixed_event.created", "timetable_fixed_event", str(row.id), _payload(row))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Fixed event conflicts with existing configuration") from exc
    db.refresh(row)
    return TimetableFixedEventResponse.model_validate(_payload(row))


@router.put("/{event_id}", response_model=TimetableFixedEventResponse, dependencies=[EDIT_ACCESS])
def update_fixed_event(event_id: int, payload: TimetableFixedEventUpdate, db: DbSession, claims: Claims) -> TimetableFixedEventResponse:
    lock_timetable_configuration(db)
    row = db.get(TimetableFixedEvent, event_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Fixed event not found")
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Fixed event changed since it was loaded; refresh before saving")
    _validate_targets(db, payload)
    _assert_no_overlap(db, payload, exclude_id=row.id)
    before = _payload(row)
    academic_year, label, target_ids, slots = _encode(payload)
    row.academic_year = academic_year
    row.label = label
    row.audience_type = payload.audience_type
    row.target_mode = payload.target_mode
    row.target_ids_json = target_ids
    row.slots_json = slots
    row.is_active = payload.is_active
    row.version += 1
    row.updated_by = int(claims["sub"])
    try:
        db.flush()
        record_event(
            db,
            int(claims["sub"]),
            "timetable.fixed_event.updated",
            "timetable_fixed_event",
            str(row.id),
            {"before": before, "after": _payload(row)},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Fixed event conflicts with existing configuration") from exc
    db.refresh(row)
    return TimetableFixedEventResponse.model_validate(_payload(row))
