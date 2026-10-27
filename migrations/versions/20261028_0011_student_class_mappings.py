"""Add controlled intake class mappings.

Revision ID: 20261028_0011
Revises: 20261028_0010
"""

import sqlalchemy as sa
from alembic import op

revision = "20261028_0011"
down_revision = "20261028_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "student_class_mappings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_workbook", sa.String(length=40), nullable=False),
        sa.Column("source_label", sa.String(length=120), nullable=False),
        sa.Column("source_key", sa.String(length=120), nullable=False),
        sa.Column("instructional_class_id", sa.Integer(), sa.ForeignKey("instructional_classes.id"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_workbook", "source_key", name="uq_student_class_mapping_source"),
        sa.CheckConstraint("source_workbook IN ('STUDENT_INTAKE_2023')", name="ck_student_class_mapping_source"),
        sa.CheckConstraint("version >= 1", name="ck_student_class_mapping_version"),
    )
    op.create_index("ix_student_class_mappings_instructional_class_id", "student_class_mappings", ["instructional_class_id"])


def downgrade() -> None:
    raise RuntimeError("Student intake class mappings must be preserved; use a forward migration or verified recovery")
