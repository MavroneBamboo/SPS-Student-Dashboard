"""Add managed academic year configuration and retain legacy year labels."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261103_0019"
down_revision = "20261103_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "academic_years",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=20), nullable=False, unique=True),
        sa.Column("code_key", sa.String(length=20), nullable=False, unique=True),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=True),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_academic_year_version"),
        sa.CheckConstraint(
            "(starts_on IS NULL AND ends_on IS NULL) OR (starts_on IS NOT NULL AND ends_on IS NOT NULL AND ends_on >= starts_on)",
            name="ck_academic_year_dates",
        ),
        sa.CheckConstraint(
            "is_active = false OR (starts_on IS NOT NULL AND ends_on IS NOT NULL)", name="ck_academic_year_active_configured"
        ),
    )

    bind = op.get_bind()
    legacy_years = bind.execute(
        sa.text(
            "SELECT DISTINCT upper(trim(year_value)) AS year_code FROM ("
            "SELECT academic_year AS year_value FROM students WHERE academic_year IS NOT NULL "
            "UNION ALL SELECT academic_year FROM lesson_requirements WHERE academic_year IS NOT NULL "
            "UNION ALL SELECT academic_year FROM scheduling_rules WHERE academic_year IS NOT NULL "
            "UNION ALL SELECT academic_year FROM timetable_versions WHERE academic_year IS NOT NULL"
            ") years WHERE trim(year_value) <> '' ORDER BY year_code"
        )
    ).scalars()
    rows = [{"code": value, "code_key": value.casefold(), "label": value} for value in legacy_years]
    if rows:
        bind.execute(
            sa.text(
                "INSERT INTO academic_years (code, code_key, label, starts_on, ends_on, is_active, version) "
                "VALUES (:code, :code_key, :label, NULL, NULL, false, 1)"
            ),
            rows,
        )


def downgrade() -> None:
    raise RuntimeError("Academic year references preserve historical year labels; use a forward migration")
