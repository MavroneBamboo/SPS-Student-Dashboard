"""Add configurable recurring timetable overlays.

Revision ID: 20261110_0021
Revises: 20261106_0020
"""

import sqlalchemy as sa
from alembic import op

revision = "20261110_0021"
down_revision = "20261106_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "timetable_fixed_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("academic_year", sa.String(length=20), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("audience_type", sa.String(length=12), nullable=False),
        sa.Column("target_mode", sa.String(length=12), nullable=False),
        sa.Column("target_ids_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("slots_json", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(trim(academic_year)) > 0", name="ck_fixed_event_academic_year"),
        sa.CheckConstraint("length(trim(label)) > 0", name="ck_fixed_event_label"),
        sa.CheckConstraint("audience_type IN ('CLASS', 'TEACHER')", name="ck_fixed_event_audience"),
        sa.CheckConstraint("target_mode IN ('ALL', 'SELECTED')", name="ck_fixed_event_target_mode"),
        sa.CheckConstraint("version >= 1", name="ck_fixed_event_version"),
    )
    op.create_index("ix_timetable_fixed_events_academic_year", "timetable_fixed_events", ["academic_year"])
    op.create_index("ix_fixed_event_year_active", "timetable_fixed_events", ["academic_year", "is_active"])


def downgrade() -> None:
    raise RuntimeError("Timetable fixed-event history must be preserved; use a forward migration or verified recovery")
