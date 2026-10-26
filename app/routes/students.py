from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.crypto import decrypt_sensitive, encrypt_sensitive
from app.deps import Claims, DbSession, require_roles
from app.models import Student, StudentStatusHistory
from app.schemas import StudentCreate, StudentResponse, StudentStatusHistoryResponse, StudentUpdate

router = APIRouter(prefix="/students", tags=["students"])


def response(row: Student) -> StudentResponse:
    return StudentResponse(
        id=row.id,
        version=row.version,
        pris_no=row.pris_no,
        name=decrypt_sensitive(row.name_encrypted) or "",
        class_name=row.class_name,
        category=row.category,
        status=row.status,
        status_effective=row.status_effective,
        date_of_birth=decrypt_sensitive(row.date_of_birth_encrypted),
    )


@router.get("", response_model=list[StudentResponse], dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator"))])
def list_students(
    db: DbSession,
    claims: Claims,
    q: str | None = Query(default=None, max_length=120),
    class_name: str | None = Query(default=None, max_length=120),
    student_status: str | None = Query(default=None, alias="status", max_length=40),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> list[StudentResponse]:
    query = select(Student).order_by(Student.pris_no)
    if class_name:
        query = query.where(Student.class_name == class_name.strip())
    if student_status:
        query = query.where(Student.status == student_status.strip().upper())
    rows = db.scalars(query).all()
    if q:
        q_lower = q.strip().lower()
        rows = [row for row in rows if q_lower in row.pris_no.lower() or q_lower in (decrypt_sensitive(row.name_encrypted) or "").lower()]
    return [response(row) for row in rows[offset : offset + limit]]


@router.get(
    "/{student_id}", response_model=StudentResponse, dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator"))]
)
def get_student(student_id: int, db: DbSession, claims: Claims) -> StudentResponse:
    row = db.get(Student, student_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return response(row)


@router.post(
    "",
    response_model=StudentResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator"))],
)
def create_student(payload: StudentCreate, db: DbSession, claims: Claims) -> StudentResponse:
    pris_no = payload.pris_no.strip().upper()
    if db.scalar(select(Student).where(Student.pris_no == pris_no)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pris No. already exists")
    row = Student(
        pris_no=pris_no,
        name_encrypted=encrypt_sensitive(payload.name.strip()),
        class_name=payload.class_name.strip(),
        category=payload.category.strip(),
        status=payload.status.strip().upper(),
        status_effective=payload.status_effective,
        date_of_birth_encrypted=encrypt_sensitive(payload.date_of_birth.isoformat() if payload.date_of_birth else None),
        created_by=int(claims["sub"]),
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Pris No. already exists") from exc
    db.add(
        StudentStatusHistory(
            student_id=row.id,
            previous_status=None,
            new_status=row.status,
            effective_date=row.status_effective or date.today(),
            changed_by=int(claims["sub"]),
        )
    )
    record_event(db, int(claims["sub"]), "student.created", "student", str(row.id))
    db.commit()
    db.refresh(row)
    return response(row)


@router.patch(
    "/{student_id}", response_model=StudentResponse, dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator"))]
)
def update_student(student_id: int, payload: StudentUpdate, db: DbSession, claims: Claims) -> StudentResponse:
    row = db.get(Student, student_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    previous_status = row.status
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Student profile changed; reload before saving")
    values = {"version": Student.version + 1}
    for field in ("class_name", "category"):
        if changes.get(field) is not None:
            values[field] = changes[field].strip()
    if "name" in changes and changes["name"] is not None:
        values["name_encrypted"] = encrypt_sensitive(changes["name"].strip())
    if "date_of_birth" in changes:
        values["date_of_birth_encrypted"] = encrypt_sensitive(changes["date_of_birth"].isoformat() if changes["date_of_birth"] else None)
    new_status = changes.get("status", previous_status).upper()
    status_changed = new_status != previous_status
    if status_changed:
        values["status"] = new_status
        values["status_effective"] = changes.get("status_effective") or date.today()
    elif "status_effective" in changes and changes["status_effective"] != row.status_effective:
        raise HTTPException(status_code=422, detail="An effective date change requires a status change")
    changed = db.execute(
        update(Student)
        .where(Student.id == student_id, Student.version == payload.expected_version)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Student profile changed; reload before saving")
    if status_changed:
        db.add(
            StudentStatusHistory(
                student_id=row.id,
                previous_status=previous_status,
                new_status=new_status,
                effective_date=values["status_effective"],
                changed_by=int(claims["sub"]),
            )
        )
    record_event(
        db,
        int(claims["sub"]),
        "student.updated",
        "student",
        str(row.id),
        {
            "fields": sorted(changes),
            "status_from": previous_status,
            "status_to": new_status,
            "previous_version": payload.expected_version,
            "version": payload.expected_version + 1,
        },
    )
    db.flush()
    db.refresh(row)
    result = response(row)
    db.commit()
    return result


@router.get("/{student_id}/status-history", dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator"))])
def status_history(student_id: int, db: DbSession, claims: Claims) -> list[StudentStatusHistoryResponse]:
    if db.get(Student, student_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    rows = db.scalars(
        select(StudentStatusHistory)
        .where(StudentStatusHistory.student_id == student_id)
        .order_by(StudentStatusHistory.effective_date, StudentStatusHistory.id)
    ).all()
    return [
        StudentStatusHistoryResponse(
            previous_status=row.previous_status, new_status=row.new_status, effective_date=row.effective_date, changed_by=row.changed_by
        )
        for row in rows
    ]
