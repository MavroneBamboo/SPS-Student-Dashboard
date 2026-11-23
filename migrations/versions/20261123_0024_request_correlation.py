"""Persist request correlation IDs on audit events.

Revision ID: 20261123_0024
Revises: 20261120_0023
"""

import sqlalchemy as sa
from alembic import op

revision = "20261123_0024"
down_revision = "20261120_0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_events", sa.Column("request_id", sa.String(length=32), nullable=True))
    op.create_index("ix_audit_events_request_id", "audit_events", ["request_id"])


def downgrade() -> None:
    raise RuntimeError("Audit correlation history must be preserved; use a forward migration or verified recovery")
