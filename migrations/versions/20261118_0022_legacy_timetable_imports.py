"""Track legacy timetable imports for idempotency and provenance.

Revision ID: 20261118_0022
Revises: 20261110_0021
"""

import sqlalchemy as sa
from alembic import op

revision = "20261118_0022"
down_revision = "20261110_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "legacy_timetable_imports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("academic_year", sa.String(length=20), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("timetable_version_id", sa.Integer(), sa.ForeignKey("timetable_versions.id"), nullable=False),
        sa.Column("imported_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("length(source_sha256) = 64", name="ck_legacy_import_sha256_length"),
        sa.UniqueConstraint("source_sha256", "academic_year", "week_start", name="uq_legacy_import_source_week"),
        sa.UniqueConstraint("timetable_version_id", name="uq_legacy_import_timetable_version"),
    )
    op.create_index("ix_legacy_timetable_imports_academic_year", "legacy_timetable_imports", ["academic_year"])
    op.create_index("ix_legacy_timetable_imports_week_start", "legacy_timetable_imports", ["week_start"])


def downgrade() -> None:
    raise RuntimeError("Legacy timetable import provenance must be preserved; use a forward migration or verified recovery")
