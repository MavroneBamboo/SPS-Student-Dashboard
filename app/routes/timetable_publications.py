from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.deps import Claims, DbSession, require_roles
from app.models import TimetableVersion
from app.routes.timetables import _view
from app.schemas import TimetableRevisionRequest
from app.timetable_lock import lock_timetable_configuration

router = APIRouter(
    prefix="/timetable",
    tags=["published timetables"],
    dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator", "Executive"))],
)
PUBLISH_ACCESS = Depends(require_roles("IT Administrator"))


def _locked_version(db: DbSession, version_id: int, expected_revision: int) -> TimetableVersion:
    lock_timetable_configuration(db)
    version = db.scalar(select(TimetableVersion).where(TimetableVersion.id == version_id).with_for_update())
    if version is None:
        raise HTTPException(status_code=404, detail="Timetable version not found")
    if version.revision != expected_revision:
        raise HTTPException(status_code=409, detail="Timetable changed; reload it before publishing")
    return version


@router.get("/published")
def list_published(
    db: DbSession,
    claims: Claims,
    academic_year: str = Query(min_length=1, max_length=20),
    week_start: date | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    query = select(TimetableVersion).where(
        TimetableVersion.is_published.is_(True),
        TimetableVersion.academic_year == academic_year.strip().upper(),
    )
    if week_start:
        query = query.where(TimetableVersion.week_start == week_start)
    versions = db.scalars(query.order_by(TimetableVersion.week_start.desc()).offset(offset).limit(limit)).all()
    return [_view(db, version) for version in versions]


@router.post("/versions/{version_id}/publish", dependencies=[PUBLISH_ACCESS])
def publish_version(version_id: int, payload: TimetableRevisionRequest, db: DbSession, claims: Claims) -> dict:
    version = _locked_version(db, version_id, payload.expected_revision)
    if version.status != "APPROVED":
        raise HTTPException(status_code=409, detail="Only an approved timetable can be published")
    current = db.scalar(
        select(TimetableVersion)
        .where(
            TimetableVersion.academic_year == version.academic_year,
            TimetableVersion.week_start == version.week_start,
            TimetableVersion.is_published.is_(True),
        )
        .with_for_update()
    )
    if current is not None and current.id == version.id:
        return _view(db, version)
    previous_version_id = current.id if current is not None else None
    if current is not None:
        current.is_published = False
        db.flush()
    version.is_published = True
    version.published_by = int(claims["sub"])
    version.published_at = datetime.now(UTC)
    try:
        record_event(
            db,
            int(claims["sub"]),
            "timetable.version.published",
            "timetable_version",
            str(version.id),
            {
                "academic_year": version.academic_year,
                "week_start": version.week_start.isoformat(),
                "revision": version.revision,
                "previous_version_id": previous_version_id,
            },
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="A timetable version for this week was published concurrently") from exc
    db.refresh(version)
    return _view(db, version)


@router.post("/versions/{version_id}/unpublish", dependencies=[PUBLISH_ACCESS])
def unpublish_version(version_id: int, payload: TimetableRevisionRequest, db: DbSession, claims: Claims) -> dict:
    version = _locked_version(db, version_id, payload.expected_revision)
    if not version.is_published:
        raise HTTPException(status_code=409, detail="This timetable version is not the current published version")
    version.is_published = False
    try:
        record_event(
            db,
            int(claims["sub"]),
            "timetable.version.unpublished",
            "timetable_version",
            str(version.id),
            {"academic_year": version.academic_year, "week_start": version.week_start.isoformat(), "revision": version.revision},
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Timetable publication changed concurrently") from exc
    db.refresh(version)
    return _view(db, version)
