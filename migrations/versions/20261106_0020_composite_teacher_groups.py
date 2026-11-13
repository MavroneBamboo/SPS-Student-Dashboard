"""Add composite teacher groups and member-aware timetable clash guards.

Revision ID: 20261106_0020
Revises: 20261104_0019
"""

import sqlalchemy as sa
from alembic import op

revision = "20261106_0020"
down_revision = "20261104_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "teachers",
        sa.Column("is_composite", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.create_table(
        "teacher_group_members",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("group_teacher_id", sa.Integer(), sa.ForeignKey("teachers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("member_teacher_id", sa.Integer(), sa.ForeignKey("teachers.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.CheckConstraint("group_teacher_id <> member_teacher_id", name="ck_teacher_group_not_self"),
        sa.UniqueConstraint("group_teacher_id", "member_teacher_id", name="uq_teacher_group_member"),
    )
    op.create_index("ix_teacher_group_members_group_teacher_id", "teacher_group_members", ["group_teacher_id"])
    op.create_index("ix_teacher_group_members_member_teacher_id", "teacher_group_members", ["member_teacher_id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
        CREATE OR REPLACE FUNCTION sps_guard_timetable_slot() RETURNS trigger LANGUAGE plpgsql VOLATILE AS $$
        DECLARE parent_status text; snapshot jsonb; requirement jsonb; period jsonb;
                parent_locked boolean; requirement_id integer; block_id integer;
                teacher_members jsonb; teacher_member_ids integer[];
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
            teacher_members := COALESCE(
                snapshot->'teachers'->NEW.teacher_id::text->'participant_ids',
                jsonb_build_array(NEW.teacher_id)
            );
            SELECT ARRAY(SELECT value::integer FROM jsonb_array_elements_text(teacher_members)) INTO teacher_member_ids;
            IF EXISTS (
                SELECT 1
                FROM timetable_slots other
                JOIN timetable_placements other_placement ON other_placement.id = other.placement_id
                CROSS JOIN LATERAL jsonb_array_elements_text(COALESCE(
                    snapshot->'teachers'->((snapshot->'requirements'->other_placement.lesson_requirement_id::text->>'teacher_id'))::text->'participant_ids',
                    jsonb_build_array((snapshot->'requirements'->other_placement.lesson_requirement_id::text->>'teacher_id')::integer)
                )) AS other_member(value)
                WHERE other.id <> NEW.id AND other.version_id = NEW.version_id AND other.weekday = NEW.weekday
                  AND (other.instructional_class_id = NEW.instructional_class_id OR other_member.value::integer = ANY(teacher_member_ids))
                  AND NEW.starts_at < other.ends_at AND other.starts_at < NEW.ends_at
            ) THEN
                RAISE EXCEPTION 'Class or teacher group member is double-booked' USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END $$
            """
        )


def downgrade() -> None:
    raise RuntimeError("Teacher groups and timetable clash protections must be preserved; use a forward migration")
