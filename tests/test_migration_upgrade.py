import os
import subprocess
import sys
from datetime import date
from pathlib import Path

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
            assert legacy_rule["binding_state"] == "UNRESOLVED"
            assert legacy_rule["instructional_class_id"] is None
            assert legacy_rule["cluster_id"] is None
            assert legacy_rule["version"] == 1
    finally:
        database.dispose()
