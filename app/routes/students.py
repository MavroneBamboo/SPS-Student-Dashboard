from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.audit import record_event
from app.crypto import decrypt_sensitive, encrypt_sensitive
from app.deps import Claims, DbSession, require_roles
from app.models import Student, StudentClassHistory, StudentStatusHistory
from app.schemas import StudentClassHistoryResponse, StudentCreate, StudentResponse, StudentStatusHistoryResponse, StudentUpdate
from app.student_catalogs import active_academic_year, active_institution, active_student_category
from app.student_class_history import class_name_on, record_class_assignment

router = APIRouter(prefix="/students", tags=["students"], dependencies=[Depends(require_roles("Operator", "Superuser"))])

ENCRYPTED_PROFILE_FIELDS = {
    "ic_number": "ic_number_encrypted",
    "gender": "gender_encrypted",
    "nationality": "nationality_encrypted",
    "citizenship": "citizenship_encrypted",
    "birthplace": "birthplace_encrypted",
    "religion": "religion_encrypted",
    "race": "race_encrypted",
    "marital_status": "marital_status_encrypted",
    "next_of_kin_name": "next_of_kin_name_encrypted",
    "next_of_kin_nric": "next_of_kin_nric_encrypted",
    "next_of_kin_relationship": "next_of_kin_relationship_encrypted",
    "next_of_kin_contact": "next_of_kin_contact_encrypted",
    "next_of_kin_address_ports": "next_of_kin_address_ports_encrypted",
    "next_of_kin_address_from_student": "next_of_kin_address_from_student_encrypted",
    "student_contact": "student_contact_encrypted",
}
PLAIN_PROFILE_FIELDS = (
    "edr_ros",
    "admission_type",
    "exam_level",
    "academic_year",
    "age_in_academic_year",
    "language_1",
    "language_2",
    "math_1",
    "math_2",
    "cpa",
    "science",
    "humanities",
    "commerce_1",
    "commerce_2",
    "commerce_3",
    "aa",
)


def response(row: Student) -> StudentResponse:
    values = {
        "id": row.id,
        "version": row.version,
        "pris_no": row.pris_no,
        "name": decrypt_sensitive(row.name_encrypted) or "",
        "class_name": row.class_name,
        "category": row.category_ref.code if row.category_ref else row.category,
        "category_id": row.category_id,
        "institution_id": row.institution_id,
        "institution_name": row.institution_ref.name if row.institution_ref else None,
        "status": row.status,
        "status_effective": row.status_effective,
        "date_of_birth": decrypt_sensitive(row.date_of_birth_encrypted),
    }
    values.update({field: decrypt_sensitive(getattr(row, column)) for field, column in ENCRYPTED_PROFILE_FIELDS.items()})
    values.update({field: getattr(row, field) for field in PLAIN_PROFILE_FIELDS})
    return StudentResponse(**values)


@router.get("", response_model=list[StudentResponse])
def list_students(
    db: DbSession,
    claims: Claims,
    q: str | None = Query(default=None, max_length=120),
    class_name: str | None = Query(default=None, max_length=120),
    institution_id: int | None = Query(default=None, ge=1),
    student_status: str | None = Query(default=None, alias="status", max_length=40),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=100),
) -> list[StudentResponse]:
    query = select(Student).order_by(Student.pris_no)
    if class_name:
        query = query.where(Student.class_name == class_name.strip())
    if institution_id is not None:
        query = query.where(Student.institution_id == institution_id)
    if student_status:
        query = query.where(Student.status == student_status.strip().upper())
    rows = db.scalars(query).all()
    if q:
        q_lower = q.strip().lower()
        rows = [row for row in rows if q_lower in row.pris_no.lower() or q_lower in (decrypt_sensitive(row.name_encrypted) or "").lower()]
    return [response(row) for row in rows[offset : offset + limit]]


@router.get("/{student_id}", response_model=StudentResponse)
def get_student(student_id: int, db: DbSession, claims: Claims) -> StudentResponse:
    row = db.get(Student, student_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Student not found")
    return response(row)


@router.post(
    "",
    response_model=StudentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_student(payload: StudentCreate, db: DbSession, claims: Claims) -> StudentResponse:
    pris_no = payload.pris_no.strip().upper()
    if db.scalar(select(Student).where(Student.pris_no == pris_no)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pris No. already exists")
    values = {field: getattr(payload, field) for field in PLAIN_PROFILE_FIELDS}
    if payload.academic_year:
        values["academic_year"] = active_academic_year(db, payload.academic_year).code
    values.update({column: encrypt_sensitive(getattr(payload, field)) for field, column in ENCRYPTED_PROFILE_FIELDS.items()})
    category = active_student_category(db, payload.category)
    institution = active_institution(db, payload.institution_id)
    class_effective_date = payload.class_effective_date or date.today()
    if class_effective_date > date.today():
        raise HTTPException(status_code=422, detail="Class effective date cannot be in the future")
    row = Student(
        pris_no=pris_no,
        name_encrypted=encrypt_sensitive(payload.name.strip()),
        class_name=payload.class_name.strip(),
        category=category.code,
        category_id=category.id,
        institution_id=institution.id if institution else None,
        status=payload.status.strip().upper(),
        status_effective=payload.status_effective,
        date_of_birth_encrypted=encrypt_sensitive(payload.date_of_birth.isoformat() if payload.date_of_birth else None),
        created_by=int(claims["sub"]),
        **values,
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
    db.add(
        StudentClassHistory(
            student_id=row.id,
            class_name=row.class_name,
            effective_date=class_effective_date,
            source="PROFILE",
            changed_by=int(claims["sub"]),
        )
    )
    record_event(db, int(claims["sub"]), "student.created", "student", str(row.id))
    db.commit()
    db.refresh(row)
    return response(row)


@router.patch("/{student_id}", response_model=StudentResponse)
def update_student(student_id: int, payload: StudentUpdate, db: DbSession, claims: Claims) -> StudentResponse:
    row = db.get(Student, student_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    changes = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
    previous_status = row.status
    if row.version != payload.expected_version:
        raise HTTPException(status_code=409, detail="Student profile changed; reload before saving")
    age_in_academic_year = changes.get("age_in_academic_year", row.age_in_academic_year)
    academic_year = changes.get("academic_year", row.academic_year)
    if age_in_academic_year is not None and not academic_year:
        raise HTTPException(status_code=422, detail="academic_year is required when age_in_academic_year is provided")
    if "academic_year" in changes and changes["academic_year"]:
        changes["academic_year"] = active_academic_year(db, changes["academic_year"]).code
    values = {"version": Student.version + 1}
    previous_class_at_effective_date = None
    class_effective_date = None
    if changes.get("class_name") is not None:
        class_effective_date = changes.get("class_effective_date") or date.today()
        previous_class_at_effective_date = class_name_on(db, row.id, class_effective_date)
        values["class_name"] = record_class_assignment(
            db,
            student_id=row.id,
            class_name=changes["class_name"].strip(),
            effective_date=class_effective_date,
            changed_by=int(claims["sub"]),
            source="PROFILE",
        )
    if "category" in changes:
        category = active_student_category(db, changes["category"])
        values["category"] = category.code
        values["category_id"] = category.id
    if "institution_id" in changes:
        institution = active_institution(db, changes["institution_id"])
        values["institution_id"] = institution.id if institution else None
    if "name" in changes and changes["name"] is not None:
        values["name_encrypted"] = encrypt_sensitive(changes["name"].strip())
    if "date_of_birth" in changes:
        values["date_of_birth_encrypted"] = encrypt_sensitive(changes["date_of_birth"].isoformat() if changes["date_of_birth"] else None)
    for field, column in ENCRYPTED_PROFILE_FIELDS.items():
        if field in changes:
            values[column] = encrypt_sensitive(changes[field])
    for field in PLAIN_PROFILE_FIELDS:
        if field in changes:
            values[field] = changes[field]
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
            "class_effective_date": (changes.get("class_effective_date") or date.today()).isoformat() if "class_name" in changes else None,
            "class_from": previous_class_at_effective_date,
            "class_to": changes.get("class_name").strip() if "class_name" in changes else None,
            "previous_version": payload.expected_version,
            "version": payload.expected_version + 1,
        },
    )
    db.flush()
    db.refresh(row)
    result = response(row)
    db.commit()
    return result


@router.get("/{student_id}/status-history")
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


@router.get("/{student_id}/class-history", response_model=list[StudentClassHistoryResponse])
def class_history(student_id: int, db: DbSession, claims: Claims) -> list[StudentClassHistoryResponse]:
    if db.get(Student, student_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    rows = db.scalars(
        select(StudentClassHistory)
        .where(StudentClassHistory.student_id == student_id)
        .order_by(StudentClassHistory.effective_date, StudentClassHistory.id)
    ).all()
    return [
        StudentClassHistoryResponse(
            class_name=row.class_name,
            effective_date=row.effective_date,
            source=row.source,
            changed_by=row.changed_by,
        )
        for row in rows
    ]
