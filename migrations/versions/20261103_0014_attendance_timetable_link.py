"""Link attendance setup and sessions to published instructional timetables.

Revision ID: 20261103_0014
Revises: 20261028_0013
"""

import sqlalchemy as sa
from alembic import op

revision = "20261103_0014"
down_revision = "20261028_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "attendance_class_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_class_name", sa.String(length=120), nullable=False),
        sa.Column("class_key", sa.String(length=120), nullable=False),
        sa.Column("instructional_class_id", sa.Integer(), sa.ForeignKey("instructional_classes.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_attendance_class_mapping_version"),
    )
    op.create_index(
        "uq_attendance_class_mapping_active_key",
        "attendance_class_mappings",
        ["class_key"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
        sqlite_where=sa.text("is_active = 1"),
    )
    op.create_index(
        "uq_attendance_class_mapping_active_instructional_class",
        "attendance_class_mappings",
        ["instructional_class_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
        sqlite_where=sa.text("is_active = 1"),
    )
    op.create_index("ix_attendance_class_mappings_instructional_class_id", "attendance_class_mappings", ["instructional_class_id"])

    with op.batch_alter_table("attendance_sessions") as batch_op:
        batch_op.add_column(sa.Column("timetable_version_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("instructional_class_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_attendance_session_timetable_version", "timetable_versions", ["timetable_version_id"], ["id"])
        batch_op.create_foreign_key(
            "fk_attendance_session_instructional_class", "instructional_classes", ["instructional_class_id"], ["id"]
        )
        batch_op.create_check_constraint(
            "ck_attendance_schedule_provenance_pair",
            "(timetable_version_id IS NULL AND instructional_class_id IS NULL) OR "
            "(timetable_version_id IS NOT NULL AND instructional_class_id IS NOT NULL)",
        )
    op.create_index("ix_attendance_sessions_timetable_version_id", "attendance_sessions", ["timetable_version_id"])
    op.create_index("ix_attendance_sessions_instructional_class_id", "attendance_sessions", ["instructional_class_id"])


def downgrade() -> None:
    raise RuntimeError("Attendance and timetable history must be preserved; use a forward migration or verified recovery")
