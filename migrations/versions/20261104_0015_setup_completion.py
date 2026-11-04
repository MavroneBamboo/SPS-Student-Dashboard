"""Persist and enforce initial Superuser setup completion."""

import sqlalchemy as sa
from alembic import op

revision = "20261104_0015"
down_revision = "20261103_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "setup_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("completed", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.CheckConstraint("id = 1", name="ck_setup_state_singleton"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO setup_state (id, completed, completed_at, completed_by)
            SELECT 1,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM users
                       WHERE role = 'Superuser' AND is_active = true AND must_change_password = false
                   ) AND EXISTS (
                       SELECT 1 FROM users
                       WHERE role = 'IT Administrator' AND is_active = true
                   ) THEN true ELSE false END,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM users
                       WHERE role = 'Superuser' AND is_active = true AND must_change_password = false
                   ) AND EXISTS (
                       SELECT 1 FROM users
                       WHERE role = 'IT Administrator' AND is_active = true
                   ) THEN CURRENT_TIMESTAMP ELSE NULL END,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM users
                       WHERE role = 'Superuser' AND is_active = true AND must_change_password = false
                   ) AND EXISTS (
                       SELECT 1 FROM users
                       WHERE role = 'IT Administrator' AND is_active = true
                   ) THEN (
                       SELECT id FROM users
                       WHERE role = 'Superuser' AND is_active = true AND must_change_password = false
                       ORDER BY id LIMIT 1
                   ) ELSE NULL END
            """
        )
    )


def downgrade() -> None:
    raise RuntimeError("Initial setup state must be preserved; use a forward migration")
