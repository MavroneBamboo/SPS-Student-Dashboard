"""Support the 2021 intake worksheet without losing its profile fields.

Revision ID: 20261104_0019
Revises: 20261104_0018
"""

import sqlalchemy as sa
from alembic import op

revision = "20261104_0019"
down_revision = "20261104_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("student_class_mappings") as batch_op:
        batch_op.drop_constraint("ck_student_class_mapping_source", type_="check")
        batch_op.create_check_constraint(
            "ck_student_class_mapping_source", "source_workbook IN ('STUDENT_INTAKE_2021', 'STUDENT_INTAKE_2023')"
        )

    with op.batch_alter_table("student_import_batches") as batch_op:
        batch_op.add_column(
            sa.Column(
                "source_workbook",
                sa.String(length=40),
                server_default=sa.text("'STUDENT_INTAKE_2023'"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_student_import_source_workbook", "source_workbook IN ('STUDENT_INTAKE_2021', 'STUDENT_INTAKE_2023')"
        )

    with op.batch_alter_table("students") as batch_op:
        batch_op.add_column(sa.Column("verification_note_encrypted", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("elective", sa.String(length=120), nullable=True))


def downgrade() -> None:
    raise RuntimeError("Student intake source and profile history must be preserved; use a forward migration or verified recovery")
