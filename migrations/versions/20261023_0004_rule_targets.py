"""Bind scheduling rules to stable resources and enforce scope conflicts.

Revision ID: 20261023_0004
Revises: 20261023_0003

Existing text-only rules remain UNRESOLVED with their original data intact.
IT must explicitly bind or archive them before their effective planning dates.
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_0004"
down_revision = "20261023_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("scheduling_rules") as batch:
        batch.add_column(sa.Column("instructional_class_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cluster_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("binding_state", sa.String(20), nullable=False, server_default="UNRESOLVED"))
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch.create_foreign_key("fk_rule_class", "instructional_classes", ["instructional_class_id"], ["id"])
        batch.create_foreign_key("fk_rule_cluster", "class_clusters", ["cluster_id"], ["id"])
        batch.drop_constraint("uq_rule_scope_start", type_="unique")
        batch.create_check_constraint(
            "ck_rule_binding",
            "(binding_state = 'UNRESOLVED' AND instructional_class_id IS NULL AND cluster_id IS NULL) OR "
            "(binding_state = 'BOUND' AND ((target_type = 'CLASS' AND instructional_class_id IS NOT NULL AND cluster_id IS NULL) OR "
            "(target_type = 'CLUSTER' AND cluster_id IS NOT NULL AND instructional_class_id IS NULL)))",
        )
        batch.create_check_constraint(
            "ck_rule_dates", "binding_state = 'UNRESOLVED' OR effective_to IS NULL OR effective_to >= effective_from"
        )
        batch.create_check_constraint("ck_rule_version", "version >= 1")
        batch.create_index("ix_scheduling_rules_instructional_class_id", ["instructional_class_id"])
        batch.create_index("ix_scheduling_rules_cluster_id", ["cluster_id"])
    if op.get_bind().dialect.name != "postgresql":
        return
    # VOLATILE trigger queries obtain fresh snapshots after acquiring the shared
    # transaction lock, including when another writer committed during the wait.
    op.execute("""
        CREATE FUNCTION sps_timetable_write_lock() RETURNS trigger
        LANGUAGE plpgsql VOLATILE AS $$
        BEGIN
            IF current_setting('transaction_isolation') <> 'read committed' THEN
                RAISE EXCEPTION 'Timetable configuration writes require READ COMMITTED isolation'
                    USING ERRCODE = '25000';
            END IF;
            PERFORM pg_advisory_xact_lock(5460051, 1);
            RETURN NULL;
        END $$
    """)
    for table in ("scheduling_rules", "class_cluster_members"):
        op.execute(f"""
            CREATE TRIGGER sps_lock_{table}
            BEFORE INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION sps_timetable_write_lock()
        """)
    op.execute("""
        CREATE FUNCTION sps_validate_rule_scope() RETURNS trigger
        LANGUAGE plpgsql VOLATILE AS $$
        BEGIN
            IF NEW.is_active AND NEW.binding_state = 'BOUND' AND EXISTS (
                SELECT 1 FROM scheduling_rules other
                WHERE other.id <> NEW.id AND other.is_active AND other.binding_state = 'BOUND'
                  AND upper(btrim(other.academic_year)) = upper(btrim(NEW.academic_year))
                  AND (NEW.effective_to IS NULL OR other.effective_from <= NEW.effective_to)
                  AND (other.effective_to IS NULL OR NEW.effective_from <= other.effective_to)
                  AND (
                    other.instructional_class_id = NEW.instructional_class_id OR other.cluster_id = NEW.cluster_id
                    OR EXISTS (
                        SELECT 1 FROM class_cluster_members m
                        WHERE (m.cluster_id = NEW.cluster_id AND m.instructional_class_id = other.instructional_class_id)
                           OR (m.cluster_id = other.cluster_id AND m.instructional_class_id = NEW.instructional_class_id)
                    )
                  )
            ) THEN
                RAISE EXCEPTION 'Duplicate or overlapping scheduling rule' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER sps_rule_scope BEFORE INSERT OR UPDATE ON scheduling_rules
        FOR EACH ROW EXECUTE FUNCTION sps_validate_rule_scope()
    """)
    op.execute("""
        CREATE FUNCTION sps_validate_cluster_rule_scope() RETURNS trigger
        LANGUAGE plpgsql VOLATILE AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM scheduling_rules class_rule JOIN scheduling_rules cluster_rule
                  ON upper(btrim(class_rule.academic_year)) = upper(btrim(cluster_rule.academic_year))
                 AND (class_rule.effective_to IS NULL OR cluster_rule.effective_from <= class_rule.effective_to)
                 AND (cluster_rule.effective_to IS NULL OR class_rule.effective_from <= cluster_rule.effective_to)
                WHERE class_rule.is_active AND cluster_rule.is_active
                  AND class_rule.binding_state = 'BOUND' AND cluster_rule.binding_state = 'BOUND'
                  AND class_rule.instructional_class_id = NEW.instructional_class_id
                  AND cluster_rule.cluster_id = NEW.cluster_id
            ) THEN
                RAISE EXCEPTION 'Cluster membership creates overlapping scheduling rules' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER sps_cluster_rule_scope BEFORE INSERT OR UPDATE ON class_cluster_members
        FOR EACH ROW EXECUTE FUNCTION sps_validate_cluster_rule_scope()
    """)


def downgrade() -> None:
    raise RuntimeError("Rule history and bindings must be preserved; recover with a verified backup or forward migration.")
