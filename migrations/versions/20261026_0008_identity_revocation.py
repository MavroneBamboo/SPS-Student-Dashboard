"""Add account-wide token revocation and case-insensitive username uniqueness."""

import sqlalchemy as sa
from alembic import op

revision = "20261026_0008"
down_revision = "20261026_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    users = sa.table("users", sa.column("username"))
    duplicate = connection.execute(
        sa.select(sa.func.lower(users.c.username)).group_by(sa.func.lower(users.c.username)).having(sa.func.count() > 1)
    ).first()
    if duplicate:
        raise RuntimeError(
            "Case-insensitive duplicate usernames require explicit IT reconciliation before upgrading; no accounts were removed"
        )
    op.add_column("users", sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"))
    op.create_index("uq_users_username_lower", "users", [sa.text("lower(username)")], unique=True)


def downgrade() -> None:
    raise RuntimeError("Identity revocation and username uniqueness must be preserved; use forward migration or verified recovery")
