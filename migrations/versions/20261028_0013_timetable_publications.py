"""Track the single currently published timetable for each academic week.

Revision ID: 20261028_0013
Revises: 20261028_0011
"""

import sqlalchemy as sa
from alembic import op

revision = "20261028_0013"
down_revision = "20261028_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "timetable_versions",
        sa.Column("is_published", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("timetable_versions", sa.Column("published_by", sa.Integer(), nullable=True))
    op.add_column("timetable_versions", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_timetable_current_publication",
        "timetable_versions",
        ["academic_year", "week_start"],
        unique=True,
        postgresql_where=sa.text("is_published IS TRUE"),
        sqlite_where=sa.text("is_published = 1"),
    )
    if op.get_bind().dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_timetable_publication_metadata_pair",
            "timetable_versions",
            "(published_by IS NULL AND published_at IS NULL) OR (published_by IS NOT NULL AND published_at IS NOT NULL)",
        )
        op.create_check_constraint(
            "ck_timetable_published_approved",
            "timetable_versions",
            "is_published = false OR (status = 'APPROVED' AND published_by IS NOT NULL AND published_at IS NOT NULL)",
        )
        op.execute("""
            CREATE OR REPLACE FUNCTION sps_guard_timetable_version() RETURNS trigger LANGUAGE plpgsql VOLATILE AS $$
            BEGIN
                IF OLD.status = 'APPROVED' THEN
                    IF TG_OP = 'UPDATE' AND
                        (NEW.id, NEW.name, NEW.academic_year, NEW.week_start, NEW.status, NEW.revision,
                         NEW.snapshot_json, NEW.created_by, NEW.approved_by, NEW.approved_at, NEW.created_at)
                        IS NOT DISTINCT FROM
                        (OLD.id, OLD.name, OLD.academic_year, OLD.week_start, OLD.status, OLD.revision,
                         OLD.snapshot_json, OLD.created_by, OLD.approved_by, OLD.approved_at, OLD.created_at)
                        AND (
                            (OLD.is_published IS FALSE AND NEW.is_published IS TRUE
                                AND NEW.published_by IS NOT NULL AND NEW.published_at IS NOT NULL)
                            OR (OLD.is_published IS TRUE AND NEW.is_published IS FALSE
                                AND (NEW.published_by, NEW.published_at) IS NOT DISTINCT FROM (OLD.published_by, OLD.published_at))
                        ) THEN
                        RETURN NEW;
                    END IF;
                    RAISE EXCEPTION 'Approved timetable content is immutable' USING ERRCODE = '23514';
                END IF;
                IF TG_OP = 'UPDATE' AND (NEW.snapshot_json IS DISTINCT FROM OLD.snapshot_json
                    OR NEW.academic_year IS DISTINCT FROM OLD.academic_year OR NEW.week_start IS DISTINCT FROM OLD.week_start) THEN
                    RAISE EXCEPTION 'Timetable snapshots are immutable' USING ERRCODE = '23514';
                END IF;
                IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
                RETURN NEW;
            END $$
        """)


def downgrade() -> None:
    raise RuntimeError("Published timetable history must be preserved; use a forward migration or verified recovery")
