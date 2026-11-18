from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql.functions import FunctionElement

from app.db import Base


class _SpaceTrim(FunctionElement):
    type = String()
    inherit_cache = True


@compiles(_SpaceTrim)
def _compile_space_trim(element, compiler, **kwargs):
    argument = compiler.process(next(iter(element.clauses)), **kwargs)
    return f"trim({argument})"


@compiles(_SpaceTrim, "postgresql")
def _compile_postgres_space_trim(element, compiler, **kwargs):
    argument = compiler.process(next(iter(element.clauses)), **kwargs)
    return f"btrim({argument})"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    role: Mapped[str] = mapped_column(String(40), default="Operator")
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


Index("uq_users_username_lower", func.lower(User.username), unique=True)


class SetupState(Base):
    __tablename__ = "setup_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_setup_state_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    completed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class SchedulingRule(Base):
    __tablename__ = "scheduling_rules"
    __table_args__ = (
        CheckConstraint(
            "(binding_state = 'UNRESOLVED' AND instructional_class_id IS NULL AND cluster_id IS NULL) OR "
            "(binding_state = 'BOUND' AND ((target_type = 'CLASS' AND instructional_class_id IS NOT NULL AND cluster_id IS NULL) OR "
            "(target_type = 'CLUSTER' AND cluster_id IS NOT NULL AND instructional_class_id IS NULL)))",
            name="ck_rule_binding",
        ),
        CheckConstraint("binding_state = 'UNRESOLVED' OR effective_to IS NULL OR effective_to >= effective_from", name="ck_rule_dates"),
        CheckConstraint("version >= 1", name="ck_rule_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    academic_year: Mapped[str] = mapped_column(String(20), index=True)
    target_type: Mapped[str] = mapped_column(String(20))
    target_key: Mapped[str] = mapped_column(String(120))
    instructional_class_id: Mapped[int | None] = mapped_column(ForeignKey("instructional_classes.id", name="fk_rule_class"), index=True)
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("class_clusters.id", name="fk_rule_cluster"), index=True)
    binding_state: Mapped[str] = mapped_column(String(20), default="UNRESOLVED")
    version: Mapped[int] = mapped_column(Integer, default=1)
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
    is_composite: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    availability_json: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TeacherGroupMember(Base):
    __tablename__ = "teacher_group_members"
    __table_args__ = (
        UniqueConstraint("group_teacher_id", "member_teacher_id", name="uq_teacher_group_member"),
        CheckConstraint("group_teacher_id <> member_teacher_id", name="ck_teacher_group_not_self"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    group_teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="CASCADE"), index=True)
    member_teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id", ondelete="RESTRICT"), index=True)
    created_by: Mapped[int] = mapped_column(Integer)


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


class StudentClassMapping(Base):
    __tablename__ = "student_class_mappings"
    __table_args__ = (
        UniqueConstraint("source_workbook", "source_key", name="uq_student_class_mapping_source"),
        CheckConstraint("source_workbook IN ('STUDENT_INTAKE_2021', 'STUDENT_INTAKE_2023')", name="ck_student_class_mapping_source"),
        CheckConstraint("version >= 1", name="ck_student_class_mapping_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_workbook: Mapped[str] = mapped_column(String(40))
    source_label: Mapped[str] = mapped_column(String(120))
    source_key: Mapped[str] = mapped_column(String(120))
    instructional_class_id: Mapped[int] = mapped_column(ForeignKey("instructional_classes.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AttendanceClassMapping(Base):
    __tablename__ = "attendance_class_mappings"
    __table_args__ = (
        Index(
            "uq_attendance_class_mapping_active_key",
            "class_key",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
            sqlite_where=text("is_active = 1"),
        ),
        Index(
            "uq_attendance_class_mapping_active_instructional_class",
            "instructional_class_id",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
            sqlite_where=text("is_active = 1"),
        ),
        CheckConstraint("version >= 1", name="ck_attendance_class_mapping_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    student_class_name: Mapped[str] = mapped_column(String(120))
    class_key: Mapped[str] = mapped_column(String(120))
    instructional_class_id: Mapped[int] = mapped_column(ForeignKey("instructional_classes.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ClassCluster(Base):
    __tablename__ = "class_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LessonRequirement(Base):
    __tablename__ = "lesson_requirements"
    __table_args__ = (
        UniqueConstraint("academic_year", "instructional_class_id", "teacher_id", "subject_id", name="uq_lesson_requirement_resources"),
        CheckConstraint("weekly_count BETWEEN 1 AND 20", name="ck_lesson_weekly_count"),
        CheckConstraint("block_length BETWEEN 1 AND 4", name="ck_lesson_block_length"),
        CheckConstraint("version >= 1", name="ck_lesson_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    academic_year: Mapped[str] = mapped_column(String(20), index=True)
    instructional_class_id: Mapped[int] = mapped_column(ForeignKey("instructional_classes.id"), index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"), index=True)
    weekly_count: Mapped[int] = mapped_column(Integer)
    block_length: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


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


class TimetableFixedEvent(Base):
    __tablename__ = "timetable_fixed_events"
    __table_args__ = (
        CheckConstraint("length(trim(academic_year)) > 0", name="ck_fixed_event_academic_year"),
        CheckConstraint("length(trim(label)) > 0", name="ck_fixed_event_label"),
        CheckConstraint("audience_type IN ('CLASS', 'TEACHER')", name="ck_fixed_event_audience"),
        CheckConstraint("target_mode IN ('ALL', 'SELECTED')", name="ck_fixed_event_target_mode"),
        CheckConstraint("version >= 1", name="ck_fixed_event_version"),
        Index("ix_fixed_event_year_active", "academic_year", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    academic_year: Mapped[str] = mapped_column(String(20), index=True)
    label: Mapped[str] = mapped_column(String(120))
    audience_type: Mapped[str] = mapped_column(String(12))
    target_mode: Mapped[str] = mapped_column(String(12))
    target_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    slots_json: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TimetableVersion(Base):
    __tablename__ = "timetable_versions"
    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_timetable_revision"),
        CheckConstraint(
            "(status = 'DRAFT' AND approved_by IS NULL AND approved_at IS NULL) OR "
            "(status = 'APPROVED' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_timetable_approval",
        ),
        CheckConstraint(
            "(published_by IS NULL AND published_at IS NULL) OR (published_by IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_timetable_publication_metadata_pair",
        ),
        CheckConstraint(
            "is_published = false OR (status = 'APPROVED' AND published_by IS NOT NULL AND published_at IS NOT NULL)",
            name="ck_timetable_published_approved",
        ),
        Index(
            "uq_timetable_current_publication",
            "academic_year",
            "week_start",
            unique=True,
            postgresql_where=text("is_published IS TRUE"),
            sqlite_where=text("is_published = 1"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    academic_year: Mapped[str] = mapped_column(String(20), index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    snapshot_json: Mapped[str] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(Integer)
    approved_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    published_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TimetableVersionClass(Base):
    __tablename__ = "timetable_version_classes"

    version_id: Mapped[int] = mapped_column(ForeignKey("timetable_versions.id"), primary_key=True)
    instructional_class_id: Mapped[int] = mapped_column(ForeignKey("instructional_classes.id"), primary_key=True)


class TimetablePlacement(Base):
    __tablename__ = "timetable_placements"
    __table_args__ = (
        UniqueConstraint("id", "version_id", "weekday", name="uq_placement_version_day"),
        CheckConstraint("weekday IN ('MON','TUE','WED','THU','FRI')", name="ck_placement_weekday"),
        CheckConstraint("start_period IN ('P1','P2','P3','P4') AND period_count BETWEEN 1 AND 4", name="ck_placement_block"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("timetable_versions.id"), index=True)
    lesson_requirement_id: Mapped[int] = mapped_column(ForeignKey("lesson_requirements.id"), index=True)
    weekday: Mapped[str] = mapped_column(String(3))
    start_period: Mapped[str] = mapped_column(String(8))
    period_count: Mapped[int] = mapped_column(Integer)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(500), default="")
    created_by: Mapped[int] = mapped_column(Integer)
    updated_by: Mapped[int] = mapped_column(Integer)


class TimetableSlot(Base):
    __tablename__ = "timetable_slots"
    __table_args__ = (
        ForeignKeyConstraint(
            ["placement_id", "version_id", "weekday"],
            ["timetable_placements.id", "timetable_placements.version_id", "timetable_placements.weekday"],
            name="fk_slot_placement",
        ),
        ForeignKeyConstraint(
            ["version_id", "instructional_class_id"],
            ["timetable_version_classes.version_id", "timetable_version_classes.instructional_class_id"],
            name="fk_slot_version_class",
        ),
        UniqueConstraint("version_id", "instructional_class_id", "weekday", "slot_code", name="uq_slot_class_period"),
        UniqueConstraint("placement_id", "slot_code", name="uq_slot_placement_period"),
        CheckConstraint("slot_code IN ('P1','P2','P3','P4')", name="ck_slot_teaching_only"),
        CheckConstraint("starts_at < ends_at", name="ck_slot_time_range"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    placement_id: Mapped[int] = mapped_column(Integer, index=True)
    version_id: Mapped[int] = mapped_column(Integer, index=True)
    instructional_class_id: Mapped[int] = mapped_column(Integer, index=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teachers.id"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id"))
    weekday: Mapped[str] = mapped_column(String(3))
    slot_code: Mapped[str] = mapped_column(String(8))
    starts_at: Mapped[time] = mapped_column(Time)
    ends_at: Mapped[time] = mapped_column(Time)


class Student(Base):
    __tablename__ = "students"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    pris_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    name_encrypted: Mapped[str] = mapped_column(Text)
    class_name: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[str] = mapped_column(String(40))
    institution: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    status_effective: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_of_birth_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    edr_ros: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ic_number_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    admission_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    exam_level: Mapped[str | None] = mapped_column(String(80), nullable=True)
    academic_year: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    age_in_academic_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gender_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    language_1: Mapped[str | None] = mapped_column(String(120), nullable=True)
    language_2: Mapped[str | None] = mapped_column(String(120), nullable=True)
    math_1: Mapped[str | None] = mapped_column(String(120), nullable=True)
    math_2: Mapped[str | None] = mapped_column(String(120), nullable=True)
    cpa: Mapped[str | None] = mapped_column(String(120), nullable=True)
    science: Mapped[str | None] = mapped_column(String(120), nullable=True)
    humanities: Mapped[str | None] = mapped_column(String(120), nullable=True)
    commerce_1: Mapped[str | None] = mapped_column(String(120), nullable=True)
    commerce_2: Mapped[str | None] = mapped_column(String(120), nullable=True)
    commerce_3: Mapped[str | None] = mapped_column(String(120), nullable=True)
    aa: Mapped[str | None] = mapped_column(String(120), nullable=True)
    nationality_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    citizenship_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    birthplace_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    religion_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    race_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    marital_status_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_of_kin_name_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_of_kin_nric_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_of_kin_relationship_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_of_kin_contact_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_of_kin_address_ports_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_of_kin_address_from_student_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    student_contact_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    verification_note_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    elective: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


Index("uq_students_pris_no_normalized", func.upper(_SpaceTrim(Student.pris_no)), unique=True)


class StudentReferenceValue(Base):
    __tablename__ = "student_reference_values"
    __table_args__ = (
        UniqueConstraint("catalog_type", "normalized_key", name="uq_student_reference_type_key"),
        CheckConstraint("catalog_type IN ('CATEGORY', 'INSTITUTION', 'ACADEMIC_YEAR')", name="ck_student_reference_type"),
        CheckConstraint("version >= 1", name="ck_student_reference_version"),
        CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from", name="ck_student_reference_dates"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    catalog_type: Mapped[str] = mapped_column(String(24), index=True)
    name: Mapped[str] = mapped_column(String(120))
    normalized_key: Mapped[str] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
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


class StudentImportBatch(Base):
    __tablename__ = "student_import_batches"
    __table_args__ = (
        CheckConstraint("status IN ('PREVIEW', 'COMMITTED', 'EXPIRED')", name="ck_student_import_status"),
        CheckConstraint("row_count >= 0 AND valid_count >= 0 AND invalid_count >= 0", name="ck_student_import_counts"),
        CheckConstraint("source_workbook IN ('STUDENT_INTAKE_2021', 'STUDENT_INTAKE_2023')", name="ck_student_import_source_workbook"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_workbook: Mapped[str] = mapped_column(
        String(40), nullable=False, default="STUDENT_INTAKE_2023", server_default="STUDENT_INTAKE_2023"
    )
    status: Mapped[str] = mapped_column(String(20), default="PREVIEW", server_default="PREVIEW", index=True)
    source_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    rows_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer)
    valid_count: Mapped[int] = mapped_column(Integer)
    invalid_count: Mapped[int] = mapped_column(Integer)
    warning_count: Mapped[int] = mapped_column(Integer)
    existing_count: Mapped[int] = mapped_column(Integer)
    new_count: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AttendanceSession(Base):
    __tablename__ = "attendance_sessions"
    __table_args__ = (
        Index("uq_session_class_date_type", "class_name", "session_date", "session_type", unique=True),
        CheckConstraint("roster_snapshot_state IN ('CAPTURED', 'LEGACY_PARTIAL')", name="ck_attendance_roster_snapshot_state"),
        CheckConstraint(
            "(timetable_version_id IS NULL AND instructional_class_id IS NULL) OR "
            "(timetable_version_id IS NOT NULL AND instructional_class_id IS NOT NULL)",
            name="ck_attendance_schedule_provenance_pair",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    session_date: Mapped[date] = mapped_column(Date, index=True)
    session_type: Mapped[str] = mapped_column(String(30))
    class_name: Mapped[str] = mapped_column(String(120), index=True)
    expected_count: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN")
    roster_snapshot_state: Mapped[str] = mapped_column(String(24), default="LEGACY_PARTIAL", server_default="LEGACY_PARTIAL")
    timetable_version_id: Mapped[int | None] = mapped_column(ForeignKey("timetable_versions.id"), nullable=True, index=True)
    instructional_class_id: Mapped[int | None] = mapped_column(ForeignKey("instructional_classes.id"), nullable=True, index=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class AttendanceRosterEntry(Base):
    __tablename__ = "attendance_roster_entries"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_attendance_roster_session_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("attendance_sessions.id"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id"), index=True)
    pris_no_snapshot: Mapped[str] = mapped_column(String(40))
    student_name_encrypted: Mapped[str] = mapped_column(Text)
    student_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("session_id", "student_id", name="uq_attendance_session_student"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
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


class LegacyTimetableImport(Base):
    __tablename__ = "legacy_timetable_imports"
    __table_args__ = (
        UniqueConstraint("source_sha256", "academic_year", "week_start", name="uq_legacy_import_source_week"),
        CheckConstraint("length(source_sha256) = 64", name="ck_legacy_import_sha256_length"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_sha256: Mapped[str] = mapped_column(String(64))
    academic_year: Mapped[str] = mapped_column(String(20), index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    timetable_version_id: Mapped[int] = mapped_column(ForeignKey("timetable_versions.id"), unique=True)
    imported_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
