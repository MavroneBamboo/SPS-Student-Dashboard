from datetime import date

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Student, StudentClassHistory, StudentStatusHistory


def class_name_on(db: Session, student_id: int, on_date: date) -> str | None:
    return db.scalar(
        select(StudentClassHistory.class_name)
        .where(StudentClassHistory.student_id == student_id, StudentClassHistory.effective_date <= on_date)
        .order_by(StudentClassHistory.effective_date.desc(), StudentClassHistory.id.desc())
        .limit(1)
    )


def record_class_assignment(
    db: Session,
    *,
    student_id: int,
    class_name: str,
    effective_date: date,
    changed_by: int,
    source: str,
) -> str:
    if effective_date > date.today():
        raise HTTPException(status_code=422, detail="Class effective date cannot be in the future")
    existing = db.scalar(
        select(StudentClassHistory)
        .where(StudentClassHistory.student_id == student_id, StudentClassHistory.effective_date == effective_date)
        .with_for_update()
    )
    if existing is None:
        db.add(
            StudentClassHistory(
                student_id=student_id,
                class_name=class_name,
                effective_date=effective_date,
                source=source,
                changed_by=changed_by,
            )
        )
    elif existing.class_name != class_name:
        existing.class_name = class_name
        existing.source = source
        existing.changed_by = changed_by

    db.flush()
    return class_name_on(db, student_id, date.today()) or class_name


def students_active_on(db: Session, on_date: date) -> list[tuple[Student, str]]:
    latest_class = (
        select(
            StudentClassHistory.student_id.label("student_id"),
            StudentClassHistory.class_name.label("class_name"),
            func.row_number()
            .over(
                partition_by=StudentClassHistory.student_id,
                order_by=(StudentClassHistory.effective_date.desc(), StudentClassHistory.id.desc()),
            )
            .label("position"),
        )
        .where(StudentClassHistory.effective_date <= on_date)
        .subquery()
    )
    latest_status = (
        select(
            StudentStatusHistory.student_id.label("student_id"),
            StudentStatusHistory.new_status.label("status"),
            func.row_number()
            .over(
                partition_by=StudentStatusHistory.student_id,
                order_by=(StudentStatusHistory.effective_date.desc(), StudentStatusHistory.id.desc()),
            )
            .label("position"),
        )
        .where(StudentStatusHistory.effective_date <= on_date)
        .subquery()
    )
    return db.execute(
        select(Student, latest_class.c.class_name)
        .join(latest_class, latest_class.c.student_id == Student.id)
        .join(latest_status, latest_status.c.student_id == Student.id)
        .where(
            latest_class.c.position == 1,
            latest_status.c.position == 1,
            latest_status.c.status == "ACTIVE",
        )
        .order_by(Student.pris_no)
        .with_for_update(of=Student)
    ).all()
