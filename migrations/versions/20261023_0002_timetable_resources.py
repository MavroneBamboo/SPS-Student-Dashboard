"""Add timetable resource profiles, clusters, and period defaults.

Revision ID: 20261023_0002
Revises: 20261023_0001
"""

from alembic import op
import sqlalchemy as sa

revision = "20261023_0002"
down_revision = "20261023_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "teachers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("short_code", sa.String(24), nullable=False),
        sa.Column("full_name", sa.String(160), nullable=False),
        sa.Column("is_adjunct", sa.Boolean(), nullable=False),
        sa.Column("availability_json", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_teachers_short_code", "teachers", ["short_code"], unique=True)
    op.create_index("ix_teachers_full_name", "teachers", ["full_name"])

    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(24), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_subjects_code", "subjects", ["code"], unique=True)
    op.create_index("ix_subjects_name", "subjects", ["name"])

    op.create_table(
        "instructional_classes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(24), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("reporting_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_instructional_classes_code", "instructional_classes", ["code"], unique=True)
    op.create_index("ix_instructional_classes_name", "instructional_classes", ["name"])

    op.create_table(
        "class_clusters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(24), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_class_clusters_code", "class_clusters", ["code"], unique=True)
    op.create_index("ix_class_clusters_name", "class_clusters", ["name"])

    op.create_table(
        "class_cluster_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cluster_id", sa.Integer(), sa.ForeignKey("class_clusters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("instructional_class_id", sa.Integer(), sa.ForeignKey("instructional_classes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.UniqueConstraint("instructional_class_id", name="uq_cluster_member_class"),
    )
    op.create_index("ix_class_cluster_members_cluster_id", "class_cluster_members", ["cluster_id"])
    op.create_index("ix_class_cluster_members_instructional_class_id", "class_cluster_members", ["instructional_class_id"])

    op.create_table(
        "period_definitions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope", sa.String(12), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("slot_code", sa.String(8), nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(80), nullable=False),
        sa.Column("starts_at", sa.String(5), nullable=True),
        sa.Column("ends_at", sa.String(5), nullable=True),
        sa.Column("is_schedulable", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("scope", "target_id", "slot_code", name="uq_period_scope_slot"),
        sa.CheckConstraint(
            "(slot_code = 'LUNCH' AND display_order = 3 AND is_schedulable = false) OR "
            "(slot_code = 'P1' AND display_order = 1 AND is_schedulable = true) OR "
            "(slot_code = 'P2' AND display_order = 2 AND is_schedulable = true) OR "
            "(slot_code = 'P3' AND display_order = 4 AND is_schedulable = true) OR "
            "(slot_code = 'P4' AND display_order = 5 AND is_schedulable = true)",
            name="ck_period_slot_lunch",
        ),
        sa.CheckConstraint(
            "(scope = 'DEFAULT' AND target_id = 0) OR (scope IN ('CLASS', 'CLUSTER') AND target_id > 0)",
            name="ck_period_scope_target",
        ),
    )
    op.create_index("ix_period_definitions_scope", "period_definitions", ["scope"])
    op.create_index("ix_period_definitions_target_id", "period_definitions", ["target_id"])

    periods = sa.table(
        "period_definitions",
        sa.column("scope", sa.String),
        sa.column("target_id", sa.Integer),
        sa.column("slot_code", sa.String),
        sa.column("display_order", sa.Integer),
        sa.column("label", sa.String),
        sa.column("starts_at", sa.String),
        sa.column("ends_at", sa.String),
        sa.column("is_schedulable", sa.Boolean),
        sa.column("is_active", sa.Boolean),
        sa.column("created_by", sa.Integer),
    )
    op.bulk_insert(
        periods,
        [
            {
                "scope": "DEFAULT",
                "target_id": 0,
                "slot_code": "P1",
                "display_order": 1,
                "label": "Period 1",
                "starts_at": "08:30",
                "ends_at": "10:15",
                "is_schedulable": True,
                "is_active": True,
                "created_by": 0,
            },
            {
                "scope": "DEFAULT",
                "target_id": 0,
                "slot_code": "P2",
                "display_order": 2,
                "label": "Period 2",
                "starts_at": "10:15",
                "ends_at": "12:00",
                "is_schedulable": True,
                "is_active": True,
                "created_by": 0,
            },
            {
                "scope": "DEFAULT",
                "target_id": 0,
                "slot_code": "LUNCH",
                "display_order": 3,
                "label": "Lunch",
                "starts_at": "12:00",
                "ends_at": "13:25",
                "is_schedulable": False,
                "is_active": True,
                "created_by": 0,
            },
            {
                "scope": "DEFAULT",
                "target_id": 0,
                "slot_code": "P3",
                "display_order": 4,
                "label": "Period 3",
                "starts_at": "13:25",
                "ends_at": "15:10",
                "is_schedulable": True,
                "is_active": True,
                "created_by": 0,
            },
            {
                "scope": "DEFAULT",
                "target_id": 0,
                "slot_code": "P4",
                "display_order": 5,
                "label": "Period 4",
                "starts_at": "15:10",
                "ends_at": "16:55",
                "is_schedulable": True,
                "is_active": True,
                "created_by": 0,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("period_definitions")
    op.drop_table("class_cluster_members")
    op.drop_table("class_clusters")
    op.drop_table("instructional_classes")
    op.drop_table("subjects")
    op.drop_table("teachers")
