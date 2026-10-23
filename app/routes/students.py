from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.crypto import decrypt_sensitive, encrypt_sensitive
from app.deps import Claims, DbSession, require_roles
from app.models import Student
from app.schemas import StudentCreate, StudentResponse

router = APIRouter(prefix="/students", tags=["students"])


def response(row: Student) -> StudentResponse:
    return StudentResponse(id=row.id, pris_no=row.pris_no, name=decrypt_sensitive(row.name_encrypted) or "", class_name=row.class_name, category=row.category, status=row.status, status_effective=row.status_effective, date_of_birth=decrypt_sensitive(row.date_of_birth_encrypted))


@router.get("", response_model=list[StudentResponse])
def list_students(db: DbSession, claims: Claims, q: str | None = Query(default=None, max_length=120), class_name: str | None = Query(default=None, max_length=120), student_status: str | None = Query(default=None, alias="status", max_length=40)) -> list[StudentResponse]:
    query = select(Student).order_by(Student.pris_no)
    if class_name:
        query = query.where(Student.class_name == class_name)
    if student_status:
        query = query.where(Student.status == student_status)
    rows = db.scalars(query).all()
    if q:
        q_lower = q.lower()
        rows = [row for row in rows if q_lower in row.pris_no.lower() or q_lower in (decrypt_sensitive(row.name_encrypted) or "").lower()]
    return [response(row) for row in rows]


@router.post("", response_model=StudentResponse, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_roles("Superuser", "IT Administrator", "Operator"))])
def create_student(payload: StudentCreate, db: DbSession, claims: Claims) -> StudentResponse:
    pris_no = payload.pris_no.strip().upper()
    if db.scalar(select(Student).where(Student.pris_no == pris_no)) is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Pris No. already exists")
    row = Student(pris_no=pris_no, name_encrypted=encrypt_sensitive(payload.name.strip()), class_name=payload.class_name.strip(), category=payload.category.strip(), status=payload.status.strip().upper(), status_effective=payload.status_effective, date_of_birth_encrypted=encrypt_sensitive(payload.date_of_birth.isoformat() if payload.date_of_birth else None), created_by=int(claims["sub"]))
    db.add(row)
    db.commit()
    db.refresh(row)
    return response(row)
