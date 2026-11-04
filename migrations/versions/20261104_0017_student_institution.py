"""Add optional institution to student profiles.

Revision ID: 20261104_0017
Revises: 20261104_0016
"""

import sqlalchemy as sa
from alembic import op

revision = "20261104_0017"
down_revision = "20261104_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("students", sa.Column("institution", sa.String(length=120), nullable=True))
    op.create_index("ix_students_institution", "students", ["institution"])


def downgrade() -> None:
    raise RuntimeError("Student institution values must be preserved; use a forward migration or verified recovery")
