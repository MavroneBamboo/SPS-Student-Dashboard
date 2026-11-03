"""Track effective-dated student class assignments."""

from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from alembic import op

revision = "20261103_0017"
down_revision = "20261103_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "student_class_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("class_name", sa.String(length=120), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("changed_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("student_id", "effective_date", name="uq_student_class_history_date"),
        sa.CheckConstraint("source IN ('BASELINE', 'PROFILE', 'IMPORT')", name="ck_student_class_history_source"),
    )
    op.create_index("ix_student_class_history_student_id", "student_class_history", ["student_id"])
    op.create_index("ix_student_class_history_effective_date", "student_class_history", ["effective_date"])

    history = sa.table(
        "student_class_history",
        sa.column("student_id", sa.Integer),
        sa.column("class_name", sa.String),
        sa.column("effective_date", sa.Date),
        sa.column("source", sa.String),
        sa.column("changed_by", sa.Integer),
    )
    students = sa.table(
        "students",
        sa.column("id", sa.Integer),
        sa.column("class_name", sa.String),
    )
    rollout_date = date.today()
    bind = op.get_bind()
    baseline_rows = [
        {
            "student_id": student_id,
            "class_name": class_name,
            "effective_date": rollout_date,
            "source": "BASELINE",
            "changed_by": None,
        }
        for student_id, class_name in bind.execute(sa.select(students.c.id, students.c.class_name))
    ]
    if baseline_rows:
        bind.execute(history.insert(), baseline_rows)


def downgrade() -> None:
    raise RuntimeError("Student class history is required to preserve attendance rosters; use a forward migration")
