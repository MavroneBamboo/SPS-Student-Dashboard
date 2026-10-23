"""Persist lesson requirements with stable resource references and edit versions.

Revision ID: 20261023_0003
Revises: 20261023_0002
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_0003"
down_revision = "20261023_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lesson_requirements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("academic_year", sa.String(20), nullable=False),
        sa.Column("instructional_class_id", sa.Integer(), sa.ForeignKey("instructional_classes.id"), nullable=False),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("weekly_count", sa.Integer(), nullable=False),
        sa.Column("block_length", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("academic_year", "instructional_class_id", "teacher_id", "subject_id", name="uq_lesson_requirement_resources"),
        sa.CheckConstraint("weekly_count BETWEEN 1 AND 20", name="ck_lesson_weekly_count"),
        sa.CheckConstraint("block_length BETWEEN 1 AND 4", name="ck_lesson_block_length"),
        sa.CheckConstraint("version >= 1", name="ck_lesson_version"),
    )
    for column in ("academic_year", "instructional_class_id", "teacher_id", "subject_id"):
        op.create_index(f"ix_lesson_requirements_{column}", "lesson_requirements", [column])


def downgrade() -> None:
    raise RuntimeError("Lesson requirements must be preserved; recover using a verified backup or a forward migration.")
