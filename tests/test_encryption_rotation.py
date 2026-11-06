import os
from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import crypto
from app.config import Settings
from app.encryption_rotation import rotate_encrypted_data
from app.models import AttendanceRosterEntry, AttendanceSession, Base, Student, StudentImportBatch, User


def test_keyring_reads_legacy_and_key_identified_values(monkeypatch):
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    old_cipher = Fernet(old_key.encode())
    monkeypatch.setattr(
        crypto,
        "get_settings",
        lambda: Settings(app_encryption_key=new_key, app_encryption_previous_keys=old_key),
    )

    legacy = old_cipher.encrypt(b"legacy name").decode()
    current = crypto.encrypt_sensitive("new name")
    assert crypto.decrypt_sensitive(legacy) == "legacy name"
    assert crypto.decrypt_sensitive(current) == "new name"
    assert crypto.is_current_encryption(current)
    assert not crypto.is_current_encryption(legacy)

    legacy_bytes = old_cipher.encrypt(b"legacy workbook")
    encrypted_bytes = crypto.encrypt_sensitive_bytes(b"new workbook")
    assert crypto.decrypt_sensitive_bytes(legacy_bytes) == b"legacy workbook"
    assert crypto.decrypt_sensitive_bytes(encrypted_bytes) == b"new workbook"


def test_rotation_is_read_only_by_default_and_covers_all_encrypted_storage(monkeypatch):
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    old_cipher = Fernet(old_key.encode())
    monkeypatch.setattr(
        crypto,
        "get_settings",
        lambda: Settings(app_encryption_key=new_key, app_encryption_previous_keys=old_key),
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        student = Student(
            pris_no="ROTATE-001",
            name_encrypted=old_cipher.encrypt(b"Protected Student").decode(),
            date_of_birth_encrypted=old_cipher.encrypt(b"2000-01-02").decode(),
            class_name="A4 A",
            category="OP",
            status="ACTIVE",
            created_by=1,
        )
        db.add(student)
        db.flush()
        roster = AttendanceRosterEntry(
            session_id=1,
            student_id=student.id,
            pris_no_snapshot="ROTATE-001",
            student_name_encrypted=old_cipher.encrypt(b"Protected Student").decode(),
            created_by=1,
        )
        batch = StudentImportBatch(
            status="PREVIEW",
            source_ciphertext=old_cipher.encrypt(b"workbook bytes"),
            rows_ciphertext=old_cipher.encrypt(b"staged rows"),
            row_count=0,
            valid_count=0,
            invalid_count=0,
            warning_count=0,
            existing_count=0,
            new_count=0,
            created_by=1,
        )
        purged_batch = StudentImportBatch(
            status="EXPIRED",
            source_ciphertext=None,
            rows_ciphertext=None,
            payload_purged_at=datetime.now(UTC),
            row_count=1,
            valid_count=1,
            invalid_count=0,
            warning_count=0,
            existing_count=0,
            new_count=1,
            created_by=1,
        )
        db.add_all([roster, batch, purged_batch])
        db.commit()

        original_name = student.name_encrypted
        dry_run = rotate_encrypted_data(db, apply=False)
        assert dry_run == {
            "encrypted_values_verified": 5,
            "values_to_rotate": 5,
            "attendance_roster_entries_values_to_rotate": 1,
            "student_import_batches_values_to_rotate": 2,
            "students_values_to_rotate": 2,
        }
        assert student.name_encrypted == original_name
        assert not crypto.is_current_encryption(student.name_encrypted)

        applied = rotate_encrypted_data(db, apply=True)
        assert applied["values_to_rotate"] == 5
        db.commit()
        db.expire_all()
        saved_student = db.scalar(select(Student).where(Student.pris_no == "ROTATE-001"))
        saved_roster = db.scalar(select(AttendanceRosterEntry))
        saved_batch = db.scalar(select(StudentImportBatch))
        assert crypto.decrypt_sensitive(saved_student.name_encrypted) == "Protected Student"
        assert crypto.decrypt_sensitive(saved_student.date_of_birth_encrypted) == "2000-01-02"
        assert crypto.decrypt_sensitive(saved_roster.student_name_encrypted) == "Protected Student"
        assert crypto.decrypt_sensitive_bytes(saved_batch.source_ciphertext) == b"workbook bytes"
        assert crypto.decrypt_sensitive_bytes(saved_batch.rows_ciphertext) == b"staged rows"

        verified = rotate_encrypted_data(db, apply=False)
        assert verified["values_to_rotate"] == 0
        assert verified["encrypted_values_verified"] == 5
    engine.dispose()


def test_unknown_key_identifier_fails_closed(monkeypatch):
    monkeypatch.setattr(crypto, "get_settings", lambda: Settings(app_encryption_key=Fernet.generate_key().decode()))
    with pytest.raises(ValueError, match="Unable to decrypt sensitive value"):
        crypto.decrypt_sensitive("spsenc:v1:unknown:invalid-token")


def test_unreadable_value_aborts_rotation_without_partial_commit(monkeypatch):
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    old_cipher = Fernet(old_key.encode())
    monkeypatch.setattr(
        crypto,
        "get_settings",
        lambda: Settings(app_encryption_key=new_key, app_encryption_previous_keys=old_key),
    )
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        student = Student(
            pris_no="ROTATE-ROLLBACK-001",
            name_encrypted=old_cipher.encrypt(b"Protected Student").decode(),
            class_name="A4 A",
            category="OP",
            status="ACTIVE",
            created_by=1,
        )
        batch = StudentImportBatch(
            status="PREVIEW",
            source_ciphertext=b"unreadable ciphertext",
            rows_ciphertext=old_cipher.encrypt(b"staged rows"),
            row_count=0,
            valid_count=0,
            invalid_count=0,
            warning_count=0,
            existing_count=0,
            new_count=0,
            created_by=1,
        )
        db.add_all([student, batch])
        db.commit()
        original_ciphertext = student.name_encrypted

        with pytest.raises(ValueError, match="Unable to decrypt sensitive value"):
            try:
                rotate_encrypted_data(db, apply=True)
            except ValueError:
                db.rollback()
                raise

        db.expire_all()
        saved = db.scalar(select(Student).where(Student.pris_no == "ROTATE-ROLLBACK-001"))
        assert saved.name_encrypted == original_ciphertext
        assert not crypto.is_current_encryption(saved.name_encrypted)
    engine.dispose()


def test_rotation_on_postgresql_when_disposable_test_url_is_configured(monkeypatch):
    database_url = os.getenv("ENCRYPTION_ROTATION_TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("set ENCRYPTION_ROTATION_TEST_DATABASE_URL to an isolated disposable PostgreSQL database")

    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()
    old_cipher = Fernet(old_key.encode())
    monkeypatch.setattr(
        crypto,
        "get_settings",
        lambda: Settings(app_encryption_key=new_key, app_encryption_previous_keys=old_key),
    )
    engine = create_engine(database_url)
    schema_name = f"rotation_{uuid4().hex}"
    schema_engine = engine.execution_options(schema_translate_map={None: schema_name})
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
        Base.metadata.create_all(schema_engine)
        with Session(schema_engine) as db:
            user = User(username="rotation-test", password_hash="not-used", role="Superuser", must_change_password=False)
            db.add(user)
            db.flush()
            student = Student(
                pris_no="ROTATE-PG-001",
                name_encrypted=old_cipher.encrypt(b"Protected Student").decode(),
                date_of_birth_encrypted=old_cipher.encrypt(b"2000-01-02").decode(),
                class_name="A4 A",
                category="OP",
                status="ACTIVE",
                created_by=user.id,
            )
            db.add(student)
            db.flush()
            session = AttendanceSession(
                session_date=date(2026, 1, 1),
                session_type="MORNING",
                class_name="A4 A",
                expected_count=1,
                status="OPEN",
                roster_snapshot_state="CAPTURED",
                created_by=user.id,
            )
            db.add(session)
            db.flush()
            db.add(
                AttendanceRosterEntry(
                    session_id=session.id,
                    student_id=student.id,
                    pris_no_snapshot=student.pris_no,
                    student_name_encrypted=old_cipher.encrypt(b"Protected Student").decode(),
                    created_by=user.id,
                )
            )
            db.add(
                StudentImportBatch(
                    status="PREVIEW",
                    source_ciphertext=old_cipher.encrypt(b"workbook bytes"),
                    rows_ciphertext=old_cipher.encrypt(b"staged rows"),
                    row_count=0,
                    valid_count=0,
                    invalid_count=0,
                    warning_count=0,
                    existing_count=0,
                    new_count=0,
                    created_by=user.id,
                )
            )
            db.commit()

            assert rotate_encrypted_data(db, apply=False)["values_to_rotate"] == 5
            assert rotate_encrypted_data(db, apply=True)["values_to_rotate"] == 5
            db.commit()
            assert rotate_encrypted_data(db, apply=False)["values_to_rotate"] == 0
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE')
        engine.dispose()
