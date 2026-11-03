import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import LargeBinary, MetaData, create_engine, inspect, select


def _migration_environment(database_url: str) -> dict[str, str]:
    return {**os.environ, "DATABASE_URL": database_url, "DATABASE_ADMIN_URL": database_url}


def test_resource_revision_upgrade_preserves_existing_profiles_and_students(tmp_path):
    """Data preservation rehearsal; PostgreSQL DDL/parity is exercised separately in CI."""
    database_url = f"sqlite:///{(tmp_path / 'upgrade.db').as_posix()}"
    environment = _migration_environment(database_url)
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
            assert connection.execute(select(upgraded.tables["users"].c.token_version)).scalar_one() == 0
            assert legacy_rule["binding_state"] == "UNRESOLVED"
            assert legacy_rule["instructional_class_id"] is None
            assert legacy_rule["cluster_id"] is None
            assert legacy_rule["version"] == 1
    finally:
        database.dispose()


@pytest.mark.parametrize("duplicate", [False, True])
def test_identity_upgrade_preserves_users_or_refuses_casefold_duplicates(tmp_path, duplicate):
    database_url = f"sqlite:///{(tmp_path / 'identity-upgrade.db').as_posix()}"
    environment = _migration_environment(database_url)
    root = Path(__file__).resolve().parents[1]

    def migrate(revision):
        return subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision], cwd=root, env=environment, capture_output=True, text=True, check=False
        )

    assert migrate("20261026_0007").returncode == 0
    database = create_engine(database_url)
    try:
        metadata = MetaData()
        metadata.reflect(bind=database)
        users = metadata.tables["users"]
        with database.begin() as connection:
            connection.execute(
                users.insert().values(
                    username="Identity.User", password_hash="preserved-hash", role="Operator", must_change_password=False, is_active=True
                )
            )
            if duplicate:
                connection.execute(
                    users.insert().values(
                        username="identity.user", password_hash="other-hash", role="Executive", must_change_password=True, is_active=True
                    )
                )
            original = list(connection.execute(select(users)))
        upgraded = migrate("head")
        if duplicate:
            assert upgraded.returncode != 0 and "explicit IT reconciliation" in upgraded.stderr
            assert "token_version" not in {column["name"] for column in inspect(database).get_columns("users")}
        else:
            assert upgraded.returncode == 0, upgraded.stderr
            assert migrate("head").returncode == 0
        with database.connect() as connection:
            assert list(connection.execute(select(users))) == original
            if not duplicate:
                current = MetaData()
                current.reflect(bind=connection)
                assert connection.execute(select(current.tables["users"].c.token_version)).scalar_one() == 0
                assert "auth_sessions" in current.tables
                assert connection.execute(select(current.tables["auth_sessions"])).all() == []
    finally:
        database.dispose()


def test_extended_student_profile_upgrade_preserves_existing_encrypted_profile(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'extended-profile-upgrade.db').as_posix()}"
    environment = _migration_environment(database_url)
    root = Path(__file__).resolve().parents[1]

    def migrate(revision):
        return subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision], cwd=root, env=environment, capture_output=True, text=True, check=False
        )

    assert migrate("20261026_0008").returncode == 0
    database = create_engine(database_url)
    try:
        before_metadata = MetaData()
        before_metadata.reflect(bind=database)
        students = before_metadata.tables["students"]
        original = {
            "pris_no": "EXTENDED-UPGRADE-1",
            "name_encrypted": "preserved-name-ciphertext",
            "class_name": "Preserved Class",
            "category": "OP",
            "status": "ACTIVE",
            "status_effective": date(2026, 1, 2),
            "date_of_birth_encrypted": "preserved-dob-ciphertext",
            "version": 4,
            "created_by": 1,
        }
        with database.begin() as connection:
            connection.execute(students.insert().values(**original))

        upgraded = migrate("head")
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
        assert migrate("head").returncode == 0
        after_metadata = MetaData()
        after_metadata.reflect(bind=database)
        with database.connect() as connection:
            saved = connection.execute(select(after_metadata.tables["students"])).mappings().one()
            assert all(saved[key] == value for key, value in original.items())
            for column in (
                "ic_number_encrypted",
                "gender_encrypted",
                "nationality_encrypted",
                "citizenship_encrypted",
                "birthplace_encrypted",
                "religion_encrypted",
                "race_encrypted",
                "marital_status_encrypted",
                "next_of_kin_name_encrypted",
                "next_of_kin_nric_encrypted",
                "next_of_kin_relationship_encrypted",
                "next_of_kin_contact_encrypted",
                "next_of_kin_address_ports_encrypted",
                "next_of_kin_address_from_student_encrypted",
                "student_contact_encrypted",
                "edr_ros",
                "admission_type",
                "exam_level",
                "academic_year",
                "age_in_academic_year",
                "language_1",
                "language_2",
                "math_1",
                "math_2",
                "cpa",
                "science",
                "humanities",
                "commerce_1",
                "commerce_2",
                "commerce_3",
                "aa",
            ):
                assert saved[column] is None
    finally:
        database.dispose()


def test_student_reference_catalog_migration_maps_legacy_category_without_rewriting_profile(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'student-catalog-upgrade.db').as_posix()}"
    environment = _migration_environment(database_url)
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

    migrate("20261103_0015")
    database = create_engine(database_url)
    try:
        metadata = MetaData()
        metadata.reflect(bind=database)
        users, students = metadata.tables["users"], metadata.tables["students"]
        with database.begin() as connection:
            connection.execute(
                users.insert().values(
                    id=1,
                    username="catalog-upgrade-admin",
                    password_hash="fixture-hash",
                    role="IT Administrator",
                    must_change_password=False,
                    is_active=True,
                )
            )
            connection.execute(
                students.insert().values(
                    pris_no="CATALOG-UPGRADE-1",
                    name_encrypted="preserved-ciphertext",
                    class_name="Preserved Class",
                    category="  op  ",
                    status="ACTIVE",
                    created_by=1,
                )
            )

        migrate("head")
        migrate("head")
        upgraded = MetaData()
        upgraded.reflect(bind=database)
        with database.connect() as connection:
            saved = connection.execute(select(upgraded.tables["students"])).mappings().one()
            category = (
                connection.execute(
                    select(upgraded.tables["student_categories"]).where(upgraded.tables["student_categories"].c.id == saved["category_id"])
                )
                .mappings()
                .one()
            )
            assert saved["category"] == "  op  "
            assert saved["name_encrypted"] == "preserved-ciphertext"
            assert category["code"] == "OP" and category["code_key"] == "op"
            assert set(connection.execute(select(upgraded.tables["student_categories"].c.code)).scalars()) == {"OP", "RT"}
    finally:
        database.dispose()


def test_student_class_history_migration_records_only_a_rollout_baseline(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'student-class-history-upgrade.db').as_posix()}"
    environment = _migration_environment(database_url)
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

    migrate("20261103_0016")
    database = create_engine(database_url)
    try:
        metadata = MetaData()
        metadata.reflect(bind=database)
        students = metadata.tables["students"]
        with database.begin() as connection:
            connection.execute(
                students.insert().values(
                    pris_no="CLASS-HISTORY-UPGRADE-1",
                    name_encrypted="preserved-ciphertext",
                    class_name="Baseline Class",
                    category="OP",
                    status="ACTIVE",
                    created_by=1,
                )
            )
        migrate("head")
        migrate("head")
        upgraded = MetaData()
        upgraded.reflect(bind=database)
        with database.connect() as connection:
            rows = connection.execute(select(upgraded.tables["student_class_history"])).mappings().all()
            assert len(rows) == 1
            assert rows[0]["class_name"] == "Baseline Class"
            assert rows[0]["effective_date"] == date.today()
            assert rows[0]["source"] == "BASELINE"
            assert rows[0]["changed_by"] is None
    finally:
        database.dispose()


def test_student_import_upgrade_adds_encrypted_staging_without_touching_profiles(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'student-import-upgrade.db').as_posix()}"
    environment = _migration_environment(database_url)
    root = Path(__file__).resolve().parents[1]

    def migrate(revision):
        return subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision], cwd=root, env=environment, capture_output=True, text=True, check=False
        )

    assert migrate("20261027_0009").returncode == 0
    database = create_engine(database_url)
    try:
        metadata = MetaData()
        metadata.reflect(bind=database)
        users, students = metadata.tables["users"], metadata.tables["students"]
        original = {
            "pris_no": "IMPORT-UPGRADE-1",
            "name_encrypted": "existing-encrypted-name",
            "class_name": "Preserved Import Class",
            "category": "OP",
            "status": "ACTIVE",
            "ic_number_encrypted": "existing-encrypted-ic",
            "created_by": 1,
        }
        with database.begin() as connection:
            connection.execute(
                users.insert().values(
                    id=1,
                    username="import-upgrade",
                    password_hash="preserved-hash",
                    role="Operator",
                    must_change_password=False,
                    is_active=True,
                )
            )
            connection.execute(students.insert().values(**original))
        upgraded = migrate("head")
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
        assert migrate("head").returncode == 0
        after = MetaData()
        after.reflect(bind=database)
        assert "student_import_batches" in after.tables
        columns = {column["name"]: column["type"] for column in inspect(database).get_columns("student_import_batches")}
        assert isinstance(columns["source_ciphertext"], LargeBinary)
        with database.connect() as connection:
            saved = connection.execute(select(after.tables["students"])).mappings().one()
            assert all(saved[key] == value for key, value in original.items())
            assert connection.execute(select(after.tables["student_import_batches"])).first() is None
    finally:
        database.dispose()


def test_student_import_upgrade_refuses_normalized_identifier_duplicates_without_changes(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'student-import-duplicates.db').as_posix()}"
    environment = _migration_environment(database_url)
    root = Path(__file__).resolve().parents[1]

    def migrate(revision):
        return subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision], cwd=root, env=environment, capture_output=True, text=True, check=False
        )

    assert migrate("20261027_0009").returncode == 0
    database = create_engine(database_url)
    try:
        metadata = MetaData()
        metadata.reflect(bind=database)
        students = metadata.tables["students"]
        with database.begin() as connection:
            for id_, pris_no in ((1, "DUPLICATE-IMPORT"), (2, " duplicate-import ")):
                connection.execute(
                    students.insert().values(
                        id=id_,
                        pris_no=pris_no,
                        name_encrypted=f"preserved-{id_}",
                        class_name="Legacy",
                        category="OP",
                        status="ACTIVE",
                        created_by=1,
                    )
                )
            original = list(connection.execute(select(students)))
        upgraded = migrate("head")
        assert upgraded.returncode != 0 and "Normalized duplicate Pris No." in upgraded.stderr
        with database.connect() as connection:
            assert list(connection.execute(select(students))) == original
            assert "student_import_batches" not in inspect(database).get_table_names()
            assert "uq_students_pris_no_normalized" not in {index["name"] for index in inspect(database).get_indexes("students")}
    finally:
        database.dispose()


def test_student_class_mapping_upgrade_preserves_existing_profiles(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'student-class-mappings.db').as_posix()}"
    environment = _migration_environment(database_url)
    root = Path(__file__).resolve().parents[1]

    def migrate(revision):
        return subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision], cwd=root, env=environment, capture_output=True, text=True, check=False
        )

    assert migrate("20261028_0010").returncode == 0
    database = create_engine(database_url)
    try:
        metadata = MetaData()
        metadata.reflect(bind=database)
        users, students = metadata.tables["users"], metadata.tables["students"]
        with database.begin() as connection:
            connection.execute(
                users.insert().values(
                    id=1,
                    username="class-mapping-upgrade-admin",
                    password_hash="fixture-hash",
                    role="IT Administrator",
                    must_change_password=False,
                    is_active=True,
                )
            )
            connection.execute(
                students.insert().values(
                    id=1,
                    pris_no="CLASS-MAPPING-UPGRADE",
                    name_encrypted="preserved-ciphertext",
                    class_name="Legacy class label",
                    category="OP",
                    status="ACTIVE",
                    created_by=1,
                )
            )
            before = connection.execute(select(students)).mappings().one()
        upgraded = migrate("head")
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
        assert migrate("head").returncode == 0
        after = MetaData()
        after.reflect(bind=database)
        assert "student_class_mappings" in after.tables
        columns = {column["name"] for column in inspect(database).get_columns("student_class_mappings")}
        assert {"source_workbook", "source_label", "source_key", "instructional_class_id", "version", "is_active"} <= columns
        with database.connect() as connection:
            saved = connection.execute(select(after.tables["students"])).mappings().one()
            assert all(saved[column] == value for column, value in before.items())
            assert saved["category_id"] is not None
            assert connection.execute(select(after.tables["student_class_mappings"])).first() is None
    finally:
        database.dispose()


@pytest.mark.parametrize("duplicate", [False, True])
def test_attendance_upgrade_preserves_records_or_refuses_ambiguous_sessions(tmp_path, duplicate):
    database_url = f"sqlite:///{(tmp_path / 'attendance-upgrade.db').as_posix()}"
    environment = _migration_environment(database_url)
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
                session = current.tables["attendance_sessions"]
                roster = current.tables["attendance_roster_entries"]
                assert connection.execute(select(session.c.roster_snapshot_state)).scalar_one() == "LEGACY_PARTIAL"
                entry = connection.execute(select(roster)).mappings().one()
                assert entry["session_id"] == 1
                assert entry["student_id"] == 1
                assert entry["pris_no_snapshot"] == "ATT-UPGRADE"
                assert entry["student_name_encrypted"] == "preserved-ciphertext"
                assert entry["student_status"] is None
                assert entry["created_by"] == 1
    finally:
        database.dispose()


def test_attendance_timetable_link_migration_preserves_existing_sessions(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'attendance-timetable-upgrade.db').as_posix()}"
    environment = _migration_environment(database_url)
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

    migrate("20261028_0013")
    database = create_engine(database_url)
    try:
        before = MetaData()
        before.reflect(bind=database)
        sessions = before.tables["attendance_sessions"]
        session_values = {
            "session_date": date(2026, 10, 19),
            "session_type": "MORNING",
            "class_name": "Preserved Attendance Class",
            "expected_count": 2,
            "notes": "Preserve prior session",
            "status": "OPEN",
            "version": 3,
            "roster_snapshot_state": "LEGACY_PARTIAL",
            "created_by": 7,
        }
        with database.begin() as connection:
            connection.execute(sessions.insert().values(id=42, **session_values))

        migrate("head")
        with database.connect() as connection:
            after = MetaData()
            after.reflect(bind=connection)
            current = after.tables["attendance_sessions"]
            row = connection.execute(select(current).where(current.c.id == 42)).mappings().one()
            for key, value in session_values.items():
                assert row[key] == value
            assert row["timetable_version_id"] is None
            assert row["instructional_class_id"] is None
    finally:
        database.dispose()


def test_student_import_retention_migration_preserves_encrypted_batch_payloads(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'student-import-retention-upgrade.db').as_posix()}"
    environment = _migration_environment(database_url)
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

    migrate("20261103_0014")
    database = create_engine(database_url)
    try:
        before = MetaData()
        before.reflect(bind=database)
        users = before.tables["users"]
        batches = before.tables["student_import_batches"]
        batch_values = {
            "status": "PREVIEW",
            "source_ciphertext": b"encrypted-original-workbook",
            "rows_ciphertext": b"encrypted-parsed-rows",
            "row_count": 3,
            "valid_count": 2,
            "invalid_count": 1,
            "warning_count": 0,
            "existing_count": 0,
            "new_count": 2,
            "created_by": 1,
        }
        with database.begin() as connection:
            connection.execute(
                users.insert().values(
                    id=1,
                    username="retention-upgrade",
                    password_hash="fixture-hash",
                    role="IT Administrator",
                    must_change_password=False,
                    is_active=True,
                )
            )
            connection.execute(batches.insert().values(id=70, **batch_values))
            original = connection.execute(select(batches).where(batches.c.id == 70)).mappings().one()

        migrate("head")
        after = MetaData()
        after.reflect(bind=database)
        current = after.tables["student_import_batches"]
        with database.connect() as connection:
            upgraded = connection.execute(select(current).where(current.c.id == 70)).mappings().one()
            for key, value in original.items():
                assert upgraded[key] == value
            assert upgraded["payload_purged_at"] is None
        columns = {column["name"]: column for column in inspect(database).get_columns("student_import_batches")}
        assert columns["source_ciphertext"]["nullable"] is True
        assert columns["rows_ciphertext"]["nullable"] is True
        assert columns["payload_purged_at"]["nullable"] is True
    finally:
        database.dispose()
