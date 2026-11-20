"""Prevent overlapping full-day and half-day attendance sessions."""

import sqlalchemy as sa
from alembic import op

revision = "20261120_0023"
down_revision = "20261118_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    invalid_type = connection.execute(
        sa.text(
            """
            SELECT 1 FROM attendance_sessions
            WHERE session_type NOT IN ('MORNING', 'AFTERNOON', 'FULL_DAY')
            LIMIT 1
            """
        )
    ).first()
    overlap = connection.execute(
        sa.text(
            """
            SELECT 1
            FROM attendance_sessions
            GROUP BY upper(trim(class_name)), session_date
            HAVING sum(CASE WHEN session_type = 'MORNING' THEN 1 ELSE 0 END) > 1
                OR sum(CASE WHEN session_type = 'AFTERNOON' THEN 1 ELSE 0 END) > 1
                OR (sum(CASE WHEN session_type = 'FULL_DAY' THEN 1 ELSE 0 END) > 0 AND count(*) > 1)
            LIMIT 1
            """
        )
    ).first()
    if invalid_type or overlap:
        raise RuntimeError(
            "Existing invalid or overlapping attendance sessions require explicit IT reconciliation before upgrading; no rows were removed"
        )

    if connection.dialect.name == "sqlite":
        with op.batch_alter_table("attendance_sessions") as batch:
            batch.drop_index("uq_session_class_date_type")
            batch.create_check_constraint("ck_attendance_session_type", "session_type IN ('MORNING', 'AFTERNOON', 'FULL_DAY')")
    else:
        op.drop_index("uq_session_class_date_type", table_name="attendance_sessions")
        op.create_check_constraint(
            "ck_attendance_session_type",
            "attendance_sessions",
            "session_type IN ('MORNING', 'AFTERNOON', 'FULL_DAY')",
        )
    period_filter = "session_type IN ('MORNING', 'FULL_DAY')"
    op.create_index(
        "uq_attendance_session_morning_scope",
        "attendance_sessions",
        [sa.text("upper(trim(class_name))"), "session_date"],
        unique=True,
        postgresql_where=sa.text(period_filter),
        sqlite_where=sa.text(period_filter),
    )
    period_filter = "session_type IN ('AFTERNOON', 'FULL_DAY')"
    op.create_index(
        "uq_attendance_session_afternoon_scope",
        "attendance_sessions",
        [sa.text("upper(trim(class_name))"), "session_date"],
        unique=True,
        postgresql_where=sa.text(period_filter),
        sqlite_where=sa.text(period_filter),
    )


def downgrade() -> None:
    raise RuntimeError("Attendance session granularity must be preserved; use a forward migration or verified recovery")
