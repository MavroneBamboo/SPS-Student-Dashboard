"""Add encrypted staging for read-only legacy timetable packages."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261103_0020"
down_revision = "20261103_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legacy_timetable_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("source_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="REVIEW_REQUIRED", nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source_sha256", name="uq_legacy_timetable_import_sha256"),
        sa.CheckConstraint(
            "status IN ('REVIEW_REQUIRED', 'READY_FOR_IMPORT', 'IMPORTED', 'REJECTED')",
            name="ck_legacy_timetable_import_status",
        ),
    )
    op.create_index("ix_legacy_timetable_imports_status", "legacy_timetable_imports", ["status"])
    op.create_index("ix_legacy_timetable_imports_created_by", "legacy_timetable_imports", ["created_by"])


def downgrade() -> None:
    raise RuntimeError("Legacy timetable import evidence must be preserved; use a forward migration")
