import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import MetaData, create_engine, inspect, select


def test_resource_revision_upgrade_preserves_existing_profiles_and_students(tmp_path):
    """Data preservation rehearsal; PostgreSQL DDL/parity is exercised separately in CI."""
    database_url = f"sqlite:///{(tmp_path / 'upgrade.db').as_posix()}"
    environment = {**os.environ, "DATABASE_URL": database_url}
    root = Path(__file__).resolve().parents[1]

    def migrate(revision):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    migrate("20261023_0002")
    database = create_engine(database_url)
    try:
        metadata = MetaData()
        metadata.reflect(bind=database)
        users, students, teachers, rules = (metadata.tables[name] for name in ("users", "students", "teachers", "scheduling_rules"))
        with database.begin() as connection:
            connection.execute(
                users.insert().values(
                    id=1,
                    username="upgrade-admin",
                    password_hash="fixture-hash",
                    role="IT Administrator",
                    must_change_password=False,
                    is_active=True,
                )
            )
            connection.execute(
                students.insert().values(
                    pris_no="UPGRADE-1",
                    name_encrypted="preserve-ciphertext",
                    class_name="Upgrade Class",
                    category="OP",
                    status="ACTIVE",
                    created_by=1,
                )
            )
            connection.execute(
                teachers.insert().values(
                    short_code="UPGRADE",
                    full_name="Upgrade Teacher",
                    is_adjunct=False,
                    availability_json='{"MON":["P1"]}',
                    is_active=True,
                    created_by=1,
                )
            )
            connection.execute(
                rules.insert().values(
                    academic_year="2026",
                    target_type="CLASS",
                    target_key="Legacy display name",
                    effective_from=date(2026, 1, 1),
                    rule_json='{"maxLessonsPerDay":4}',
                    is_active=True,
                    created_by=1,
                )
            )
            snapshots = {table.name: list(connection.execute(select(table))) for table in (users, students, teachers, rules)}
        migrate("head")
        migrate("head")
        assert "lesson_requirements" in inspect(database).get_table_names()
        with database.connect() as connection:
            for table in (users, students, teachers, rules):
                assert list(connection.execute(select(table))) == snapshots[table.name]
            upgraded = MetaData()
            upgraded.reflect(bind=connection)
            legacy_rule = connection.execute(select(upgraded.tables["scheduling_rules"])).mappings().one()
            assert connection.execute(select(upgraded.tables["students"].c.version)).scalar_one() == 1
            assert legacy_rule["binding_state"] == "UNRESOLVED"
            assert legacy_rule["instructional_class_id"] is None
            assert legacy_rule["cluster_id"] is None
            assert legacy_rule["version"] == 1
    finally:
        database.dispose()


@pytest.mark.parametrize("duplicate", [False, True])
def test_attendance_upgrade_preserves_records_or_refuses_ambiguous_sessions(tmp_path, duplicate):
    database_url = f"sqlite:///{(tmp_path / 'attendance-upgrade.db').as_posix()}"
    environment = {**os.environ, "DATABASE_URL": database_url}
    root = Path(__file__).resolve().parents[1]

    def migrate(revision):
        return subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision], cwd=root, env=environment, capture_output=True, text=True, check=False
        )

    initial = migrate("20261026_0006")
    assert initial.returncode == 0, initial.stderr
    database = create_engine(database_url)
    try:
        metadata = MetaData()
        metadata.reflect(bind=database)
        students, sessions, records = (metadata.tables[name] for name in ("students", "attendance_sessions", "attendance_records"))
        with database.begin() as connection:
            connection.execute(
                students.insert().values(
                    id=1,
                    pris_no="ATT-UPGRADE",
                    name_encrypted="preserved-ciphertext",
                    class_name="Legacy Attend",
                    category="OP",
                    status="ACTIVE",
                    created_by=1,
                )
            )
            payload = {
                "session_date": date(2026, 10, 20),
                "session_type": "MORNING",
                "class_name": "Legacy Attend",
                "expected_count": 1,
                "status": "OPEN",
                "created_by": 1,
            }
            connection.execute(sessions.insert().values(id=1, **payload))
            if duplicate:
                connection.execute(sessions.insert().values(id=2, **payload))
            connection.execute(
                records.insert().values(
                    session_id=1, student_id=1, attendance_status="ABSENT", correction_reason="Preserved reason", created_by=1, updated_by=1
                )
            )
            before = {table.name: list(connection.execute(select(table))) for table in (students, sessions, records)}
        upgraded = migrate("head")
        if duplicate:
            assert upgraded.returncode != 0 and "explicit IT reconciliation" in upgraded.stderr
            assert "version" not in {column["name"] for column in inspect(database).get_columns("attendance_sessions")}
        else:
            assert upgraded.returncode == 0, upgraded.stderr
            assert migrate("head").returncode == 0
        with database.connect() as connection:
            for table in (students, sessions, records):
                assert list(connection.execute(select(table))) == before[table.name]
            if not duplicate:
                current = MetaData()
                current.reflect(bind=connection)
                for table_name in ("attendance_sessions", "attendance_records"):
                    assert connection.execute(select(current.tables[table_name].c.version)).scalar_one() == 1
    finally:
        database.dispose()
