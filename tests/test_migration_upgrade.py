import os
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
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
        assert "institution" in {column["name"] for column in inspect(database).get_columns("students")}
        with database.connect() as connection:
            for table in (users, students, teachers, rules):
                assert list(connection.execute(select(table))) == snapshots[table.name]
            upgraded = MetaData()
            upgraded.reflect(bind=connection)
            legacy_rule = connection.execute(select(upgraded.tables["scheduling_rules"])).mappings().one()
            reference_values = upgraded.tables["student_reference_values"]
            seeded_values = {
                (row["catalog_type"], row["name"])
                for row in connection.execute(select(reference_values.c.catalog_type, reference_values.c.name)).mappings()
            }
            assert connection.execute(select(upgraded.tables["students"].c.version)).scalar_one() == 1
            assert connection.execute(select(upgraded.tables["students"].c.institution)).scalar_one() is None
            assert connection.execute(select(upgraded.tables["users"].c.token_version)).scalar_one() == 0
            assert legacy_rule["binding_state"] == "UNRESOLVED"
            assert legacy_rule["instructional_class_id"] is None
            assert legacy_rule["cluster_id"] is None
            assert legacy_rule["version"] == 1
            assert ("CATEGORY", "OP") in seeded_values
            assert ("ACADEMIC_YEAR", "2026") in seeded_values
    finally:
        database.dispose()


@pytest.mark.parametrize("has_completed_setup", [False, True])
def test_setup_completion_migration_marks_new_or_already_configured_installation(tmp_path, has_completed_setup):
    database_url = f"sqlite:///{(tmp_path / f'setup-{has_completed_setup}.db').as_posix()}"
    environment = _migration_environment(database_url)
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20261103_0014"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    database = create_engine(database_url)
    try:
        with database.begin() as connection:
            users = sa.table(
                "users",
                sa.column("id", sa.Integer()),
                sa.column("username", sa.String()),
                sa.column("password_hash", sa.String()),
                sa.column("role", sa.String()),
                sa.column("must_change_password", sa.Boolean()),
                sa.column("is_active", sa.Boolean()),
            )
            connection.execute(
                users.insert().values(
                    id=1,
                    username="bootstrap-admin",
                    password_hash="irrelevant-test-hash",
                    role="Superuser",
                    must_change_password=not has_completed_setup,
                    is_active=True,
                )
            )
            if has_completed_setup:
                connection.execute(
                    users.insert().values(
                        id=2,
                        username="named-it-admin",
                        password_hash="irrelevant-test-hash",
                        role="IT Administrator",
                        must_change_password=True,
                        is_active=True,
                    )
                )
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        with database.connect() as connection:
            setup = connection.execute(sa.text("SELECT completed, completed_by FROM setup_state WHERE id = 1")).one()
        assert bool(setup.completed) is has_completed_setup
        assert setup.completed_by == (1 if has_completed_setup else None)
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


def test_attendance_granularity_upgrade_refuses_overlapping_rows_without_deleting_them(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'attendance-granularity-upgrade.db').as_posix()}"
    environment = _migration_environment(database_url)
    root = Path(__file__).resolve().parents[1]
    migrate_to_previous = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "20261118_0022"],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert migrate_to_previous.returncode == 0, migrate_to_previous.stdout + migrate_to_previous.stderr
    database = create_engine(database_url)
    try:
        metadata = MetaData()
        metadata.reflect(bind=database)
        sessions = metadata.tables["attendance_sessions"]
        with database.begin() as connection:
            connection.execute(
                sessions.insert(),
                [
                    {
                        "session_date": date(2026, 11, 18),
                        "session_type": session_type,
                        "class_name": "Overlap Class",
                        "expected_count": 2,
                        "status": "OPEN",
                        "version": 1,
                        "roster_snapshot_state": "LEGACY_PARTIAL",
                        "created_by": 1,
                    }
                    for session_type in ("MORNING", "FULL_DAY")
                ],
            )
            original_rows = list(connection.execute(select(sessions)))

        upgraded = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert upgraded.returncode != 0
        assert "invalid or overlapping attendance sessions" in upgraded.stderr
        with database.connect() as connection:
            assert list(connection.execute(select(sessions))) == original_rows
            version = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one()
            assert version == "20261118_0022"
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


def test_import_retention_migration_preserves_existing_payloads_and_allows_expired_previews(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'student-import-retention-upgrade.db').as_posix()}"
    environment = _migration_environment(database_url)
    root = Path(__file__).resolve().parents[1]

    def migrate(revision):
        return subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision], cwd=root, env=environment, capture_output=True, text=True, check=False
        )

    upgraded = migrate("20261104_0017")
    assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
    database = create_engine(database_url)
    try:
        metadata = MetaData()
        metadata.reflect(bind=database)
        users = metadata.tables["users"]
        batches = metadata.tables["student_import_batches"]
        original = {
            "status": "PREVIEW",
            "source_ciphertext": b"encrypted-source-payload",
            "rows_ciphertext": b"encrypted-row-payload",
            "row_count": 1,
            "valid_count": 1,
            "invalid_count": 0,
            "warning_count": 0,
            "existing_count": 0,
            "new_count": 1,
            "created_by": 1,
        }
        with database.begin() as connection:
            connection.execute(
                users.insert().values(
                    id=1,
                    username="retention-upgrade",
                    password_hash="preserved-hash",
                    role="Operator",
                    must_change_password=False,
                    is_active=True,
                )
            )
            connection.execute(batches.insert().values(id=1, **original))

        upgraded = migrate("head")
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
        assert migrate("head").returncode == 0
        after = MetaData()
        after.reflect(bind=database)
        columns = {column["name"]: column for column in inspect(database).get_columns("student_import_batches")}
        assert columns["source_ciphertext"]["nullable"] and columns["rows_ciphertext"]["nullable"]
        assert "payload_purged_at" in columns
        with database.begin() as connection:
            saved = (
                connection.execute(select(after.tables["student_import_batches"]).where(after.tables["student_import_batches"].c.id == 1))
                .mappings()
                .one()
            )
            assert all(saved[key] == value for key, value in original.items())
            connection.execute(
                after.tables["student_import_batches"]
                .insert()
                .values(
                    id=2,
                    status="EXPIRED",
                    source_ciphertext=None,
                    rows_ciphertext=None,
                    row_count=1,
                    valid_count=1,
                    invalid_count=0,
                    warning_count=0,
                    existing_count=0,
                    new_count=1,
                    created_by=1,
                )
            )
    finally:
        database.dispose()


def test_student_intake_2021_migration_preserves_existing_profiles_and_batches(tmp_path):
    database_url = f"sqlite:///{(tmp_path / 'student-intake-2021-upgrade.db').as_posix()}"
    environment = _migration_environment(database_url)
    root = Path(__file__).resolve().parents[1]

    def migrate(revision):
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision], cwd=root, env=environment, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stdout + result.stderr

    migrate("20261104_0018")
    database = create_engine(database_url)
    source_bytes = b"ciphertext-source-preserved"
    rows_bytes = b"ciphertext-rows-preserved"
    try:
        metadata = MetaData()
        metadata.reflect(bind=database)
        users = metadata.tables["users"]
        students = metadata.tables["students"]
        batches = metadata.tables["student_import_batches"]
        with database.begin() as connection:
            connection.execute(
                users.insert().values(
                    id=1,
                    username="intake-2021-upgrade-admin",
                    password_hash="fixture-hash",
                    role="IT Administrator",
                    must_change_password=False,
                    is_active=True,
                )
            )
            connection.execute(
                students.insert().values(
                    id=1,
                    pris_no="INTAKE-2021-UPGRADE",
                    name_encrypted="existing-profile-ciphertext",
                    class_name="Legacy class",
                    category="OP",
                    status="ACTIVE",
                    created_by=1,
                )
            )
            connection.execute(
                batches.insert().values(
                    id=1,
                    status="PREVIEW",
                    source_ciphertext=source_bytes,
                    rows_ciphertext=rows_bytes,
                    row_count=1,
                    valid_count=1,
                    invalid_count=0,
                    warning_count=0,
                    existing_count=0,
                    new_count=1,
                    created_by=1,
                )
            )
        migrate("head")
        migrate("head")
        after = MetaData()
        after.reflect(bind=database)
        checks = {item["sqltext"] for item in inspect(database).get_check_constraints("student_class_mappings")}
        assert any("STUDENT_INTAKE_2021" in check and "STUDENT_INTAKE_2023" in check for check in checks)
        with database.connect() as connection:
            upgraded_students = after.tables["students"]
            profile = connection.execute(
                select(
                    upgraded_students.c.name_encrypted,
                    upgraded_students.c.verification_note_encrypted,
                    upgraded_students.c.elective,
                )
            ).one()
            assert profile == ("existing-profile-ciphertext", None, None)
            upgraded_batch = connection.execute(select(after.tables["student_import_batches"])).mappings().one()
            assert upgraded_batch["source_workbook"] == "STUDENT_INTAKE_2023"
            assert upgraded_batch["source_ciphertext"] == source_bytes
            assert upgraded_batch["rows_ciphertext"] == rows_bytes
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
            preserved_student_fields = ("id", "pris_no", "name_encrypted", "class_name", "category", "status", "created_by")
            before = list(connection.execute(select(*(students.c[field] for field in preserved_student_fields))))
        upgraded = migrate("head")
        assert upgraded.returncode == 0, upgraded.stdout + upgraded.stderr
        assert migrate("head").returncode == 0
        after = MetaData()
        after.reflect(bind=database)
        assert "student_class_mappings" in after.tables
        columns = {column["name"] for column in inspect(database).get_columns("student_class_mappings")}
        assert {"source_workbook", "source_label", "source_key", "instructional_class_id", "version", "is_active"} <= columns
        with database.connect() as connection:
            students_after = after.tables["students"]
            assert list(connection.execute(select(*(students_after.c[field] for field in preserved_student_fields)))) == before
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
