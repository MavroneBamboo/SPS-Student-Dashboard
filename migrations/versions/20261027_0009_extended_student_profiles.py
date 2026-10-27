"""Add the remaining fields from the supported student intake workbook.

Revision ID: 20261027_0009
Revises: 20261026_0008
"""

import sqlalchemy as sa
from alembic import op

revision = "20261027_0009"
down_revision = "20261026_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = (
        ("edr_ros", sa.String(length=80)),
        ("ic_number_encrypted", sa.Text()),
        ("admission_type", sa.String(length=80)),
        ("exam_level", sa.String(length=80)),
        ("academic_year", sa.String(length=20)),
        ("age_in_academic_year", sa.Integer()),
        ("gender_encrypted", sa.Text()),
        ("language_1", sa.String(length=120)),
        ("language_2", sa.String(length=120)),
        ("math_1", sa.String(length=120)),
        ("math_2", sa.String(length=120)),
        ("cpa", sa.String(length=120)),
        ("science", sa.String(length=120)),
        ("humanities", sa.String(length=120)),
        ("commerce_1", sa.String(length=120)),
        ("commerce_2", sa.String(length=120)),
        ("commerce_3", sa.String(length=120)),
        ("aa", sa.String(length=120)),
        ("nationality_encrypted", sa.Text()),
        ("citizenship_encrypted", sa.Text()),
        ("birthplace_encrypted", sa.Text()),
        ("religion_encrypted", sa.Text()),
        ("race_encrypted", sa.Text()),
        ("marital_status_encrypted", sa.Text()),
        ("next_of_kin_name_encrypted", sa.Text()),
        ("next_of_kin_nric_encrypted", sa.Text()),
        ("next_of_kin_relationship_encrypted", sa.Text()),
        ("next_of_kin_contact_encrypted", sa.Text()),
        ("next_of_kin_address_ports_encrypted", sa.Text()),
        ("next_of_kin_address_from_student_encrypted", sa.Text()),
        ("student_contact_encrypted", sa.Text()),
    )
    for name, column_type in columns:
        op.add_column("students", sa.Column(name, column_type, nullable=True))
    op.create_index("ix_students_academic_year", "students", ["academic_year"])


def downgrade() -> None:
    raise RuntimeError("Student intake and sensitive profile data must be preserved; use forward migration or verified recovery")
