"""Version attendance transactions and prevent duplicate class/date/type sessions."""

import sqlalchemy as sa
from alembic import op

revision = "20261026_0007"
down_revision = "20261026_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    sessions = sa.table("attendance_sessions", sa.column("class_name"), sa.column("session_date"), sa.column("session_type"))
    duplicate = connection.execute(
        sa.select(sa.func.count())
        .select_from(sessions)
        .group_by(sessions.c.class_name, sessions.c.session_date, sessions.c.session_type)
        .having(sa.func.count() > 1)
    ).first()
    noncanonical = connection.execute(
        sa.select(sessions.c.class_name).where(sessions.c.class_name != sa.func.trim(sessions.c.class_name))
    ).first()
    if duplicate or noncanonical:
        raise RuntimeError(
            "Existing duplicate or untrimmed attendance sessions require explicit IT reconciliation before upgrading; no rows were removed"
        )
    for table in ("attendance_sessions", "attendance_records"):
        op.add_column(table, sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.create_index("uq_session_class_date_type", "attendance_sessions", ["class_name", "session_date", "session_type"], unique=True)


def downgrade() -> None:
    raise RuntimeError("Attendance versions and uniqueness must be preserved; use forward migration or verified recovery")
