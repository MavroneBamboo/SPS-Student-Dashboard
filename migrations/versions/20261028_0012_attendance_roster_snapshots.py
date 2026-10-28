"""Capture the attendance roster for each session.

Revision ID: 20261028_0012
Revises: 20261028_0011
"""

import sqlalchemy as sa
from alembic import op

revision = "20261028_0012"
down_revision = "20261028_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("attendance_sessions") as batch:
        batch.add_column(sa.Column("roster_snapshot_state", sa.String(length=24), server_default="LEGACY_PARTIAL", nullable=False))
        batch.create_check_constraint(
            "ck_attendance_roster_snapshot_state",
            "roster_snapshot_state IN ('CAPTURED', 'LEGACY_PARTIAL')",
        )
    op.create_table(
        "attendance_roster_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("attendance_sessions.id"), nullable=False),
        sa.Column("student_id", sa.Integer(), sa.ForeignKey("students.id"), nullable=False),
        sa.Column("pris_no_snapshot", sa.String(length=40), nullable=False),
        sa.Column("student_name_encrypted", sa.Text(), nullable=False),
        sa.Column("student_status", sa.String(length=40), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("session_id", "student_id", name="uq_attendance_roster_session_student"),
    )
    op.create_index("ix_attendance_roster_entries_session_id", "attendance_roster_entries", ["session_id"])
    op.create_index("ix_attendance_roster_entries_student_id", "attendance_roster_entries", ["student_id"])
    # Existing records prove attendance for their recorded students only. Do not
    # infer that unrecorded students were on a historical roster.
    op.execute(
        sa.text(
            """
            INSERT INTO attendance_roster_entries
                (session_id, student_id, pris_no_snapshot, student_name_encrypted, student_status, created_by)
            SELECT DISTINCT ar.session_id, s.id, s.pris_no, s.name_encrypted, NULL, a.created_by
              FROM attendance_records ar
              JOIN students s ON s.id = ar.student_id
              JOIN attendance_sessions a ON a.id = ar.session_id
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError("Attendance roster snapshots must be preserved; use a forward migration or verified recovery")
