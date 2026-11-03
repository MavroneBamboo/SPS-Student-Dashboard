"""Add controlled student categories and institutions."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261103_0016"
down_revision = "20261103_0015"
branch_labels = None
depends_on = None


def _category_code(value: str) -> str:
    return " ".join(value.strip().split())


def upgrade() -> None:
    op.create_table(
        "student_categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=40), nullable=False, unique=True),
        sa.Column("code_key", sa.String(length=120), nullable=False, unique=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_student_category_version"),
    )
    op.create_table(
        "institutions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=40), nullable=False, unique=True),
        sa.Column("code_key", sa.String(length=120), nullable=False, unique=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_institution_version"),
    )
    with op.batch_alter_table("students") as batch_op:
        batch_op.add_column(sa.Column("category_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("institution_id", sa.Integer(), nullable=True))
        batch_op.create_index("ix_students_category_id", ["category_id"])
        batch_op.create_index("ix_students_institution_id", ["institution_id"])
        batch_op.create_foreign_key("fk_students_category_id_student_categories", "student_categories", ["category_id"], ["id"])
        batch_op.create_foreign_key("fk_students_institution_id_institutions", "institutions", ["institution_id"], ["id"])

    bind = op.get_bind()
    students = sa.table(
        "students",
        sa.column("id", sa.Integer),
        sa.column("category", sa.String),
        sa.column("category_id", sa.Integer),
    )
    categories = sa.table(
        "student_categories",
        sa.column("id", sa.Integer),
        sa.column("code", sa.String),
        sa.column("code_key", sa.String),
        sa.column("name", sa.String),
        sa.column("is_active", sa.Boolean),
        sa.column("version", sa.Integer),
    )
    category_rows = bind.execute(sa.select(students.c.category).distinct().order_by(students.c.category)).scalars().all()
    codes_by_key: dict[str, str] = {"op": "OP", "rt": "RT"}
    for raw_value in category_rows:
        code = _category_code(raw_value or "")
        if code:
            codes_by_key.setdefault(code.casefold(), code)
    id_by_key: dict[str, int] = {}
    for key, code in codes_by_key.items():
        inserted = bind.execute(
            categories.insert().values(code=code, code_key=key, name=code, is_active=True, version=1).returning(categories.c.id)
        )
        id_by_key[key] = inserted.scalar_one()
    for student_id, raw_value in bind.execute(sa.select(students.c.id, students.c.category)):
        code = _category_code(raw_value or "")
        category_id = id_by_key.get(code.casefold()) if code else None
        if category_id is not None:
            bind.execute(students.update().where(students.c.id == student_id).values(category_id=category_id))


def downgrade() -> None:
    raise RuntimeError("Student reference catalog values must be preserved; use a forward migration or verified recovery")
