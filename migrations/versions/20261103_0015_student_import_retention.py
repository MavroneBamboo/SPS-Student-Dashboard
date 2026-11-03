"""Add expiry and purge metadata for encrypted student import staging payloads.

Revision ID: 20261103_0015
Revises: 20261103_0014
"""

import sqlalchemy as sa
from alembic import op

revision = "20261103_0015"
down_revision = "20261103_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("student_import_batches") as batch_op:
        batch_op.alter_column("source_ciphertext", existing_type=sa.LargeBinary(), nullable=True)
        batch_op.alter_column("rows_ciphertext", existing_type=sa.LargeBinary(), nullable=True)
        batch_op.add_column(sa.Column("payload_purged_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.drop_constraint("ck_student_import_status", type_="check")
        batch_op.create_check_constraint("ck_student_import_status", "status IN ('PREVIEW', 'COMMITTED', 'EXPIRED')")


def downgrade() -> None:
    raise RuntimeError("Import retention history must be preserved; use a forward migration or verified recovery")
