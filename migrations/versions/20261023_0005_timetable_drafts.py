"""Persist immutable timetable snapshots, lesson blocks and protected grid slots.

Revision ID: 20261023_0005
Revises: 20261023_0004
"""

import sqlalchemy as sa
from alembic import op

revision = "20261023_0005"
down_revision = "20261023_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "timetable_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("academic_year", sa.String(20), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_timetable_revision"),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND approved_by IS NULL AND approved_at IS NULL) OR "
            "(status = 'APPROVED' AND approved_by IS NOT NULL AND approved_at IS NOT NULL)",
            name="ck_timetable_approval",
        ),
    )
    for column in ("academic_year", "week_start", "status"):
        op.create_index(f"ix_timetable_versions_{column}", "timetable_versions", [column])
    op.create_table(
        "timetable_version_classes",
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("timetable_versions.id"), primary_key=True),
        sa.Column("instructional_class_id", sa.Integer(), sa.ForeignKey("instructional_classes.id"), primary_key=True),
    )
    op.create_table(
        "timetable_placements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("version_id", sa.Integer(), sa.ForeignKey("timetable_versions.id"), nullable=False),
        sa.Column("lesson_requirement_id", sa.Integer(), sa.ForeignKey("lesson_requirements.id"), nullable=False),
        sa.Column("weekday", sa.String(3), nullable=False),
        sa.Column("start_period", sa.String(8), nullable=False),
        sa.Column("period_count", sa.Integer(), nullable=False),
        sa.Column("is_locked", sa.Boolean(), nullable=False),
        sa.Column("note", sa.String(500), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.UniqueConstraint("id", "version_id", "weekday", name="uq_placement_version_day"),
        sa.CheckConstraint("weekday IN ('MON','TUE','WED','THU','FRI')", name="ck_placement_weekday"),
        sa.CheckConstraint("start_period IN ('P1','P2','P3','P4') AND period_count BETWEEN 1 AND 4", name="ck_placement_block"),
    )
    for column in ("version_id", "lesson_requirement_id"):
        op.create_index(f"ix_timetable_placements_{column}", "timetable_placements", [column])
    op.create_table(
        "timetable_slots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("placement_id", sa.Integer(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False),
        sa.Column("instructional_class_id", sa.Integer(), nullable=False),
        sa.Column("teacher_id", sa.Integer(), sa.ForeignKey("teachers.id"), nullable=False),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id"), nullable=False),
        sa.Column("weekday", sa.String(3), nullable=False),
        sa.Column("slot_code", sa.String(8), nullable=False),
        sa.Column("starts_at", sa.Time(), nullable=False),
        sa.Column("ends_at", sa.Time(), nullable=False),
        sa.ForeignKeyConstraint(
            ["placement_id", "version_id", "weekday"],
            ["timetable_placements.id", "timetable_placements.version_id", "timetable_placements.weekday"],
            name="fk_slot_placement",
        ),
        sa.ForeignKeyConstraint(
            ["version_id", "instructional_class_id"],
            ["timetable_version_classes.version_id", "timetable_version_classes.instructional_class_id"],
            name="fk_slot_version_class",
        ),
        sa.UniqueConstraint("version_id", "instructional_class_id", "weekday", "slot_code", name="uq_slot_class_period"),
        sa.UniqueConstraint("placement_id", "slot_code", name="uq_slot_placement_period"),
        sa.CheckConstraint("slot_code IN ('P1','P2','P3','P4')", name="ck_slot_teaching_only"),
        sa.CheckConstraint("starts_at < ends_at", name="ck_slot_time_range"),
    )
    for column in ("placement_id", "version_id", "instructional_class_id", "teacher_id"):
        op.create_index(f"ix_timetable_slots_{column}", "timetable_slots", [column])
    if op.get_bind().dialect.name != "postgresql":
        return
    for table in ("timetable_versions", "timetable_version_classes", "timetable_placements", "timetable_slots"):
        op.execute(f"""
            CREATE TRIGGER sps_lock_{table} BEFORE INSERT OR UPDATE OR DELETE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION sps_timetable_write_lock()
        """)
    op.execute("""
        CREATE FUNCTION sps_guard_timetable_version() RETURNS trigger LANGUAGE plpgsql VOLATILE AS $$
        BEGIN
            IF OLD.status = 'APPROVED' THEN
                RAISE EXCEPTION 'Approved timetables are immutable' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' AND (NEW.snapshot_json IS DISTINCT FROM OLD.snapshot_json
                OR NEW.academic_year IS DISTINCT FROM OLD.academic_year OR NEW.week_start IS DISTINCT FROM OLD.week_start) THEN
                RAISE EXCEPTION 'Timetable snapshots are immutable' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER sps_guard_version BEFORE UPDATE OR DELETE ON timetable_versions
        FOR EACH ROW EXECUTE FUNCTION sps_guard_timetable_version()
    """)
    op.execute("""
        CREATE FUNCTION sps_guard_timetable_class() RETURNS trigger LANGUAGE plpgsql VOLATILE AS $$
        DECLARE parent_status text; snapshot jsonb;
        BEGIN
            IF TG_OP <> 'INSERT' THEN
                RAISE EXCEPTION 'Timetable class selection is immutable' USING ERRCODE = '23514';
            END IF;
            SELECT status, snapshot_json::jsonb INTO parent_status, snapshot FROM timetable_versions WHERE id = NEW.version_id;
            IF parent_status IS DISTINCT FROM 'DRAFT' OR NOT coalesce(snapshot->'classes' ? NEW.instructional_class_id::text, false) THEN
                RAISE EXCEPTION 'Class must belong to the draft snapshot' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER sps_guard_timetable_class BEFORE INSERT OR UPDATE OR DELETE ON timetable_version_classes
        FOR EACH ROW EXECUTE FUNCTION sps_guard_timetable_class()
    """)
    op.execute("""
        CREATE FUNCTION sps_guard_timetable_placement() RETURNS trigger LANGUAGE plpgsql VOLATILE AS $$
        DECLARE parent_status text; parent_id integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN parent_id := OLD.version_id; ELSE parent_id := NEW.version_id; END IF;
            SELECT status INTO parent_status FROM timetable_versions WHERE id = parent_id;
            IF parent_status IS DISTINCT FROM 'DRAFT' THEN
                RAISE EXCEPTION 'Only draft timetables can change' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                IF NEW.version_id <> OLD.version_id THEN
                    RAISE EXCEPTION 'Placement version cannot change' USING ERRCODE = '23514';
                END IF;
                IF OLD.is_locked AND (NEW.lesson_requirement_id, NEW.weekday, NEW.start_period, NEW.period_count, NEW.note)
                    IS DISTINCT FROM (OLD.lesson_requirement_id, OLD.weekday, OLD.start_period, OLD.period_count, OLD.note) THEN
                    RAISE EXCEPTION 'Locked lesson block cannot change' USING ERRCODE = '23514';
                END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN
                IF OLD.is_locked THEN RAISE EXCEPTION 'Locked lesson block cannot be removed' USING ERRCODE = '23514'; END IF;
                RETURN OLD;
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER sps_guard_placement BEFORE INSERT OR UPDATE OR DELETE ON timetable_placements
        FOR EACH ROW EXECUTE FUNCTION sps_guard_timetable_placement()
    """)
    op.execute("""
        CREATE FUNCTION sps_guard_timetable_slot() RETURNS trigger LANGUAGE plpgsql VOLATILE AS $$
        DECLARE parent_status text; snapshot jsonb; requirement jsonb; period jsonb;
                parent_locked boolean; requirement_id integer; block_id integer;
        BEGIN
            IF TG_OP = 'DELETE' THEN block_id := OLD.placement_id; ELSE block_id := NEW.placement_id; END IF;
            IF TG_OP = 'UPDATE' AND (NEW.version_id <> OLD.version_id OR NEW.placement_id <> OLD.placement_id) THEN
                RAISE EXCEPTION 'Slot ownership cannot change' USING ERRCODE = '23514';
            END IF;
            SELECT v.status, v.snapshot_json::jsonb, p.is_locked, p.lesson_requirement_id
                INTO parent_status, snapshot, parent_locked, requirement_id
                FROM timetable_placements p JOIN timetable_versions v ON v.id = p.version_id WHERE p.id = block_id;
            IF parent_status IS DISTINCT FROM 'DRAFT' OR parent_locked THEN
                RAISE EXCEPTION 'Approved or locked timetable slots cannot change' USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            requirement := snapshot->'requirements'->requirement_id::text;
            IF requirement IS NULL OR (requirement->>'instructional_class_id')::integer IS DISTINCT FROM NEW.instructional_class_id
                OR (requirement->>'teacher_id')::integer IS DISTINCT FROM NEW.teacher_id OR (requirement->>'subject_id')::integer IS DISTINCT FROM NEW.subject_id THEN
                RAISE EXCEPTION 'Slot resources do not match the timetable snapshot' USING ERRCODE = '23514';
            END IF;
            SELECT value INTO period FROM jsonb_array_elements(snapshot->'classes'->NEW.instructional_class_id::text->'periods')
                WHERE value->>'slot_code' = NEW.slot_code;
            IF period IS NULL OR (period->>'is_schedulable')::boolean IS DISTINCT FROM true
                OR (period->>'starts_at')::time IS DISTINCT FROM NEW.starts_at OR (period->>'ends_at')::time IS DISTINCT FROM NEW.ends_at THEN
                RAISE EXCEPTION 'Slot is not a snapshotted teaching period' USING ERRCODE = '23514';
            END IF;
            IF EXISTS (SELECT 1 FROM timetable_slots other WHERE other.id <> NEW.id
                AND other.version_id = NEW.version_id AND other.weekday = NEW.weekday
                AND (other.teacher_id = NEW.teacher_id OR other.instructional_class_id = NEW.instructional_class_id)
                AND NEW.starts_at < other.ends_at AND other.starts_at < NEW.ends_at) THEN
                RAISE EXCEPTION 'Class or teacher is double-booked' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
    """)
    op.execute("""
        CREATE TRIGGER sps_guard_slot BEFORE INSERT OR UPDATE OR DELETE ON timetable_slots
        FOR EACH ROW EXECUTE FUNCTION sps_guard_timetable_slot()
    """)


def downgrade() -> None:
    raise RuntimeError("Timetable snapshots and amendments must be preserved; use a verified backup or forward migration.")
