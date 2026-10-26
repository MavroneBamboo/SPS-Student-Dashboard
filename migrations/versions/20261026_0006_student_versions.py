"""Add optimistic edit versions to preserved student profiles.

Revision ID: 20261026_0006
Revises: 20261023_0005
"""

import sqlalchemy as sa
from alembic import op

revision = "20261026_0006"
down_revision = "20261023_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("students", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))


def downgrade() -> None:
    raise RuntimeError("Student edit versions must be preserved; use a forward migration or verified recovery")
