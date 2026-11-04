"""Add IT-managed student reference catalogs and preserve existing values.

Revision ID: 20261104_0015
Revises: 20261103_0014
"""

import unicodedata

import sqlalchemy as sa
from alembic import op

revision = "20261104_0015"
down_revision = "20261103_0014"
branch_labels = None
depends_on = None


def _normalized_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _seed_values(catalog_type: str, query: str) -> None:
    connection = op.get_bind()
    seen: set[str] = set()
    for (value,) in connection.execute(sa.text(query)):
        if value is None:
            continue
        name = " ".join(str(value).split())
        if not name:
            continue
        key = _normalized_key(name)
        if key in seen:
            continue
        seen.add(key)
        connection.execute(
            sa.text(
                "INSERT INTO student_reference_values "
                "(catalog_type, name, normalized_key, is_active, version, created_at, updated_at) "
                "VALUES (:catalog_type, :name, :normalized_key, true, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"catalog_type": catalog_type, "name": name, "normalized_key": key},
        )


def upgrade() -> None:
    op.create_table(
        "student_reference_values",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("catalog_type", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("normalized_key", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=True),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("catalog_type", "normalized_key", name="uq_student_reference_type_key"),
        sa.CheckConstraint("catalog_type IN ('CATEGORY', 'INSTITUTION', 'ACADEMIC_YEAR')", name="ck_student_reference_type"),
        sa.CheckConstraint("version >= 1", name="ck_student_reference_version"),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from", name="ck_student_reference_dates"
        ),
    )
    op.create_index("ix_student_reference_values_catalog_type", "student_reference_values", ["catalog_type"])

    _seed_values("CATEGORY", "SELECT DISTINCT category FROM students ORDER BY category")
    _seed_values(
        "ACADEMIC_YEAR",
        "SELECT academic_year FROM students WHERE academic_year IS NOT NULL "
        "UNION SELECT academic_year FROM scheduling_rules "
        "UNION SELECT academic_year FROM lesson_requirements "
        "UNION SELECT academic_year FROM timetable_versions ORDER BY academic_year",
    )


def downgrade() -> None:
    raise RuntimeError("Student reference catalog data must be preserved; use a forward migration or verified recovery")
