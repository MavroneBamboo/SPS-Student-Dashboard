from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(40), default="Operator")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SchedulingRule(Base):
    __tablename__ = "scheduling_rules"
    __table_args__ = (UniqueConstraint("academic_year", "target_type", "target_key", "effective_from", name="uq_rule_scope_start"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    academic_year: Mapped[str] = mapped_column(String(20), index=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_key: Mapped[str] = mapped_column(String(120))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    rule_json: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Teacher(Base):
    __tablename__ = "teachers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    short_code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(160), index=True)
    is_adjunct: Mapped[bool] = mapped_column(Boolean, default=False)
    availability_json: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Subject(Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InstructionalClass(Base):
    __tablename__ = "instructional_classes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    reporting_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClassCluster(Base):
    __tablename__ = "class_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClassClusterMember(Base):
    __tablename__ = "class_cluster_members"
    __table_args__ = (UniqueConstraint("instructional_class_id", name="uq_cluster_member_class"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    cluster_id: Mapped[int] = mapped_column(ForeignKey("class_clusters.id", ondelete="CASCADE"), index=True)
    instructional_class_id: Mapped[int] = mapped_column(ForeignKey("instructional_classes.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int] = mapped_column(Integer)


class PeriodDefinition(Base):
    __tablename__ = "period_definitions"
    __table_args__ = (
        UniqueConstraint("scope", "target_id", "slot_code", name="uq_period_scope_slot"),
        CheckConstraint(
            "(slot_code = 'LUNCH' AND display_order = 3 AND is_schedulable = false) OR "
            "(slot_code = 'P1' AND display_order = 1 AND is_schedulable = true) OR "
            "(slot_code = 'P2' AND display_order = 2 AND is_schedulable = true) OR "
            "(slot_code = 'P3' AND display_order = 4 AND is_schedulable = true) OR "
            "(slot_code = 'P4' AND display_order = 5 AND is_schedulable = true)",
            name="ck_period_slot_lunch",
        ),
        CheckConstraint(
            "(scope = 'DEFAULT' AND target_id = 0) OR (scope IN ('CLASS', 'CLUSTER') AND target_id > 0)",
            name="ck_period_scope_target",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(12), index=True)
    target_id: Mapped[int] = mapped_column(Integer, default=0, index=True)
    slot_code: Mapped[str] = mapped_column(String(8))
    display_order: Mapped[int] = mapped_column(Integer)
    label: Mapped[str] = mapped_column(String(80))
    starts_at: Mapped[str | None] = mapped_column(String(5), nullable=True)
    ends_at: Mapped[str | None] = mapped_column(String(5), nullable=True)
    is_schedulable: Mapped[bool] = mapped_column(Boolean)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pris_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name_encrypted: Mapped[str] = mapped_column(Text)
    class_name: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), index=True)
    status_effective: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_of_birth_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class StudentStatusHistory(Base):
    __tablename__ = "student_status_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    previous_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    new_status: Mapped[str] = mapped_column(String(40))
    effective_date: Mapped[date] = mapped_column(Date)
    changed_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_date: Mapped[date] = mapped_column(Date, index=True)
    session_type: Mapped[str] = mapped_column(String(30))
    class_name: Mapped[str] = mapped_column(String(120), index=True)
    expected_count: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_attendance_session_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("attendance_sessions.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    attendance_status: Mapped[str] = mapped_column(String(20))
    correction_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int] = mapped_column(Integer, index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    entity_type: Mapped[str] = mapped_column(String(80), index=True)
    entity_id: Mapped[str] = mapped_column(String(120), index=True)
    details_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
