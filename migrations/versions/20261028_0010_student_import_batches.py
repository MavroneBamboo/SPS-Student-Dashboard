"""Add encrypted staging for student workbook imports.

Revision ID: 20261028_0010
Revises: 20261027_0009
"""

import sqlalchemy as sa
from alembic import op

revision = "20261028_0010"
down_revision = "20261027_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    students = sa.table("students", sa.column("pris_no", sa.String(length=40)))
    duplicate = connection.execute(
        sa.select(sa.func.upper(sa.func.trim(students.c.pris_no)))
        .group_by(sa.func.upper(sa.func.trim(students.c.pris_no)))
        .having(sa.func.count() > 1)
    ).first()
    if duplicate:
        raise RuntimeError(
            "Normalized duplicate Pris No. values require explicit student reconciliation before upgrading; no profiles were changed"
        )
    normalized_identifier = "upper(btrim(pris_no))" if connection.dialect.name == "postgresql" else "upper(trim(pris_no))"
    op.create_index("uq_students_pris_no_normalized", "students", [sa.text(normalized_identifier)], unique=True)
    op.create_table(
        "student_import_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PREVIEW"),
        sa.Column("source_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("rows_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("valid_count", sa.Integer(), nullable=False),
        sa.Column("invalid_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column("existing_count", sa.Integer(), nullable=False),
        sa.Column("new_count", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('PREVIEW', 'COMMITTED')", name="ck_student_import_status"),
        sa.CheckConstraint(
            "row_count >= 0 AND valid_count >= 0 AND invalid_count >= 0 AND warning_count >= 0", name="ck_student_import_counts"
        ),
    )
    op.create_index("ix_student_import_batches_status", "student_import_batches", ["status"])
    op.create_index("ix_student_import_batches_created_by", "student_import_batches", ["created_by"])


def downgrade() -> None:
    raise RuntimeError("Encrypted student import batches must be preserved; use forward migration or verified recovery")
