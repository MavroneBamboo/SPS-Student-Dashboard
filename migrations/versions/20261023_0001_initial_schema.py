"""Create the initial SPS Dashboard schema.

Revision ID: 20261023_0001
Revises:
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_0001"
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _table_exists("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(120), nullable=False),
            sa.Column("password_hash", sa.String(256), nullable=False),
            sa.Column("role", sa.String(40), nullable=False),
            sa.Column("must_change_password", sa.Boolean(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_users_username", "users", ["username"], unique=True)

    if not _table_exists("scheduling_rules"):
        op.create_table(
            "scheduling_rules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("academic_year", sa.String(20), nullable=False),
            sa.Column("target_type", sa.String(20), nullable=False),
            sa.Column("target_key", sa.String(120), nullable=False),
            sa.Column("effective_from", sa.Date(), nullable=False),
            sa.Column("effective_to", sa.Date(), nullable=True),
            sa.Column("rule_json", sa.Text(), nullable=False),
            sa.Column("is_active", sa.Boolean(), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("academic_year", "target_type", "target_key", "effective_from", name="uq_rule_scope_start"),
        )
        op.create_index("ix_scheduling_rules_academic_year", "scheduling_rules", ["academic_year"])

    if not _table_exists("students"):
        op.create_table(
            "students",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("pris_no", sa.String(40), nullable=False),
            sa.Column("name_encrypted", sa.Text(), nullable=False),
            sa.Column("class_name", sa.String(120), nullable=False),
            sa.Column("category", sa.String(40), nullable=False),
            sa.Column("status", sa.String(40), nullable=False),
            sa.Column("status_effective", sa.Date(), nullable=True),
            sa.Column("date_of_birth_encrypted", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_students_pris_no", "students", ["pris_no"], unique=True)
        op.create_index("ix_students_class_name", "students", ["class_name"])
        op.create_index("ix_students_status", "students", ["status"])

    if not _table_exists("student_status_history"):
        op.create_table(
            "student_status_history",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False),
            sa.Column("previous_status", sa.String(40), nullable=True),
            sa.Column("new_status", sa.String(40), nullable=False),
            sa.Column("effective_date", sa.Date(), nullable=False),
            sa.Column("changed_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_student_status_history_student_id", "student_status_history", ["student_id"])

    if not _table_exists("attendance_sessions"):
        op.create_table(
            "attendance_sessions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_date", sa.Date(), nullable=False),
            sa.Column("session_type", sa.String(30), nullable=False),
            sa.Column("class_name", sa.String(120), nullable=False),
            sa.Column("expected_count", sa.Integer(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index("ix_attendance_sessions_session_date", "attendance_sessions", ["session_date"])
        op.create_index("ix_attendance_sessions_class_name", "attendance_sessions", ["class_name"])

    if not _table_exists("attendance_records"):
        op.create_table(
            "attendance_records",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("session_id", sa.Integer(), sa.ForeignKey("attendance_sessions.id"), nullable=False),
            sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False),
            sa.Column("attendance_status", sa.String(20), nullable=False),
            sa.Column("correction_reason", sa.Text(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("updated_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint("session_id", "student_id", name="uq_attendance_session_student"),
        )
        op.create_index("ix_attendance_records_session_id", "attendance_records", ["session_id"])
        op.create_index("ix_attendance_records_student_id", "attendance_records", ["student_id"])

    if not _table_exists("audit_events"):
        op.create_table(
            "audit_events",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("actor_id", sa.Integer(), nullable=False),
            sa.Column("action", sa.String(80), nullable=False),
            sa.Column("entity_type", sa.String(80), nullable=False),
            sa.Column("entity_id", sa.String(120), nullable=False),
            sa.Column("details_json", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        for column in ("actor_id", "action", "entity_type", "entity_id", "created_at"):
            op.create_index(f"ix_audit_events_{column}", "audit_events", [column])


def downgrade() -> None:
    raise RuntimeError(
        "The initial schema migration is intentionally irreversible; use a verified backup or a forward migration to recover data safely."
    )
