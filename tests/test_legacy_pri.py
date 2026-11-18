import io
import json
import zipfile

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.legacy_pri import LegacyPriError, map_legacy_availability, read_legacy_pri, read_legacy_pri_bytes, reconcile_legacy_pri
from app.models import AuditEvent, LessonRequirement, TimetableVersion
from app.routes.legacy_pri import MAX_LEGACY_SOURCE_ROWS

KEY = bytes(range(16))


def encrypted_member(value):
    iv = bytes(range(16, 32))
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(json.dumps(value).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(KEY), modes.CBC(iv)).encryptor()
    return iv + encryptor.update(padded) + encryptor.finalize()


def sample_data():
    return {
        "R01.bin": [{"Id": 0, "Name": "T1", "Availability": ":".join(["1"] * 20)}],
        "R02.bin": [{"Id": 0, "Name": "S1"}],
        "R03.bin": [{"Id": 0, "Name": "C1"}],
        "R04.bin": [{"Id": 0, "Teacher": "T1", "Subject": "S1", "InstClass": "C1", "Count": 2, "Length": 1}],
        "R05.bin": [
            {"Id": 0, "Teacher": "T1", "Subject": "S1", "InstClass": "C1", "DayOfWeek": "Mon", "Period": 1},
            {"Id": 1, "Teacher": "T1", "Subject": "S1", "InstClass": "C1", "DayOfWeek": "Tue", "Period": 1},
        ],
        "R06.bin": [],
    }


def write_pri(path, members=None):
    path.write_bytes(encrypted_archive(members))


def encrypted_archive(members=None):
    values = members or sample_data()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, value in values.items():
            archive.writestr(name, encrypted_member(value))
    return buffer.getvalue()


def test_reads_exact_encrypted_json_members_without_mutating_source(tmp_path):
    source = tmp_path / "sample.pri"
    write_pri(source)
    before = source.read_bytes()
    data = read_legacy_pri(source, KEY)
    report = reconcile_legacy_pri(data)
    assert report["valid"] is True
    assert report["import_ready"] is True
    assert report["issue_counts"] == {}
    assert report["period_mapping"] == {"1": "P1", "2": "P2", "3": "LUNCH", "4": "P3", "5": "P4"}
    assert report["availability_profiles"] == {"20_teaching_slot_profiles": 1}
    assert report["counts"] == {
        "teachers": 1,
        "subjects": 1,
        "classes": 1,
        "lesson_requirements": 1,
        "placements": 2,
        "pending_lessons": 0,
    }
    assert source.read_bytes() == before


@pytest.mark.parametrize(
    "mutate,expected_code",
    [
        ("duplicate", "duplicate_class_slot"),
        ("teacher", "duplicate_teacher_slot"),
        ("reference", "invalid_placement_teacher_reference"),
        ("unplaced", "unplaced_lesson_periods"),
    ],
)
def test_reconciliation_reports_invalid_or_incomplete_schedule(tmp_path, mutate, expected_code):
    path = tmp_path / "sample.pri"
    values = sample_data()
    if mutate == "duplicate":
        values["R05.bin"][1]["DayOfWeek"] = "Mon"
    elif mutate == "teacher":
        values["R05.bin"][1]["InstClass"] = "C2"
        values["R05.bin"][1]["DayOfWeek"] = "Mon"
        values["R03.bin"].append({"Id": 1, "Name": "C2"})
    elif mutate == "reference":
        values["R05.bin"][0]["Teacher"] = "UNKNOWN"
    elif mutate == "unplaced":
        values["R05.bin"].pop()
    write_pri(path, values)
    report = reconcile_legacy_pri(read_legacy_pri(path, KEY))
    assert report["valid"] is False
    assert expected_code in report["issue_counts"]
    issue = next(issue for issue in report["issues"] if issue["code"] == expected_code)
    if mutate == "unplaced":
        assert issue == {"code": expected_code, "source": "lesson_requirement", "count": 1}
    else:
        assert issue["source"] == "placement"
        assert issue["row"] == 1


def test_rejects_unexpected_member_set(tmp_path):
    path = tmp_path / "bad.pri"
    values = sample_data()
    values.pop("R06.bin")
    write_pri(path, values)
    with pytest.raises(LegacyPriError, match="exactly R01.bin"):
        read_legacy_pri(path, KEY)


def test_rejects_invalid_key_size(tmp_path):
    path = tmp_path / "sample.pri"
    write_pri(path)
    with pytest.raises(LegacyPriError, match="AES key"):
        read_legacy_pri(path, b"short")


def test_reports_missing_placement_teacher_without_fabricating_a_clash(tmp_path):
    path = tmp_path / "sample.pri"
    values = sample_data()
    values["R05.bin"][0]["Teacher"] = ""
    write_pri(path, values)
    report = reconcile_legacy_pri(read_legacy_pri(path, KEY))
    assert report["issue_counts"]["missing_placement_teacher"] == 1
    assert "invalid_placement_teacher_reference" not in report["issue_counts"]
    assert "duplicate_teacher_slot" not in report["issue_counts"]


@pytest.mark.parametrize("availability_size", [20, 25])
def test_classifies_legacy_availability_profiles_and_blocks_ambiguous_shape(tmp_path, availability_size):
    path = tmp_path / "sample.pri"
    values = sample_data()
    values["R01.bin"][0]["Availability"] = ":".join(["1"] * availability_size)
    write_pri(path, values)

    report = reconcile_legacy_pri(read_legacy_pri(path, KEY))

    expected_profile = "20_teaching_slot_profiles" if availability_size == 20 else "25_period_position_profiles"
    assert report["availability_profiles"] == {expected_profile: 1}
    assert "invalid_teacher_availability" not in report["issue_counts"]
    if availability_size == 20:
        assert report["valid"] is True
        assert "legacy_availability_mapping_required" not in report["issue_counts"]
    else:
        assert report["valid"] is False
        assert report["import_ready"] is False
        assert report["issue_counts"]["legacy_availability_mapping_required"] == 1


def test_maps_legacy_availability_in_day_major_ui_order():
    flags = ["0"] * 20
    flags[0] = "1"  # Monday, first teaching period
    flags[7] = "1"  # Tuesday, fourth teaching period
    flags[19] = "1"  # Friday, fourth teaching period

    mapped = map_legacy_availability(":".join(flags))

    assert mapped == {
        "MON": ["P1"],
        "TUE": ["P4"],
        "WED": [],
        "THU": [],
        "FRI": ["P4"],
    }


def test_does_not_guess_25_flag_availability_mapping():
    assert map_legacy_availability(":".join(["1"] * 25)) is None


def test_blank_teacher_lunch_row_is_reviewable_not_a_lesson(tmp_path):
    path = tmp_path / "sample.pri"
    values = sample_data()
    values["R05.bin"][0].update({"Teacher": "", "Period": 3})
    write_pri(path, values)

    report = reconcile_legacy_pri(read_legacy_pri(path, KEY))

    assert report["issue_counts"]["lunch_entry_requires_review"] == 1
    assert "missing_placement_teacher" not in report["issue_counts"]
    assert "lesson_in_lunch_slot" not in report["issue_counts"]
    assert report["issue_counts"]["unplaced_lesson_periods"] == 1


def test_teacher_assigned_lunch_row_is_reported_as_a_conflict(tmp_path):
    path = tmp_path / "sample.pri"
    values = sample_data()
    values["R05.bin"][0]["Period"] = 3
    write_pri(path, values)

    report = reconcile_legacy_pri(read_legacy_pri(path, KEY))

    assert report["issue_counts"]["lesson_in_lunch_slot"] == 1
    assert report["issue_counts"]["unplaced_lesson_periods"] == 1


def test_read_legacy_pri_bytes_matches_read_only_path_parser(tmp_path):
    source = tmp_path / "sample.pri"
    archive_bytes = encrypted_archive()
    source.write_bytes(archive_bytes)

    assert read_legacy_pri_bytes(archive_bytes, KEY) == read_legacy_pri(source, KEY)


@pytest.fixture
def configured_legacy_key(monkeypatch):
    monkeypatch.setenv("LEGACY_PRI_KEY_HEX", KEY.hex())
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_legacy_project_preflight_is_role_limited_audited_and_redacted(lesson_context, configured_legacy_key):
    client, headers, _ = lesson_context
    archive_bytes = encrypted_archive()

    response = client.post(
        "/api/v1/timetable/legacy-projects/validate",
        content=archive_bytes,
        headers={**headers["admin"], "Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 200
    report = response.json()
    assert report["valid"] is True
    assert report["counts"]["teachers"] == 1
    assert report["issues"] == []
    assert "T1" not in response.text
    assert "C1" not in response.text
    assert "S1" not in response.text
    for role in ("operator", "executive"):
        rejected = client.post(
            "/api/v1/timetable/legacy-projects/validate",
            content=archive_bytes,
            headers={**headers[role], "Content-Type": "application/octet-stream"},
        )
        assert rejected.status_code == 403

    with SessionLocal() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "timetable.legacy_project.validated"))
        assert event is not None
        assert event.entity_type == "legacy_timetable_project"
        assert "T1" not in event.details_json
        assert "archive" not in event.details_json.lower()


def test_legacy_project_inspection_reveals_source_labels_only_to_it_and_superuser(lesson_context, configured_legacy_key):
    client, headers, _ = lesson_context
    archive_bytes = encrypted_archive()

    inspected = client.post(
        "/api/v1/timetable/legacy-projects/inspect",
        content=archive_bytes,
        headers={**headers["admin"], "Content-Type": "application/octet-stream"},
    )

    assert inspected.status_code == 200
    payload = inspected.json()
    assert payload["resources"]["teachers"][0]["name"] == "T1"
    assert payload["resources"]["teachers"][0]["availability_profile"] == "20-slot profile"
    assert payload["resources"]["subjects"][0]["name"] == "S1"
    assert payload["resources"]["classes"][0]["name"] == "C1"
    assert payload["lesson_requirements"][0] == {
        "source_index": 0,
        "teacher": "T1",
        "subject": "S1",
        "class": "C1",
        "weekly_count": 2,
        "block_length": 1,
    }
    assert payload["placements"][0] == {
        "source_index": 0,
        "class": "C1",
        "teacher": "T1",
        "subject": "S1",
        "weekday": "Mon",
        "period": 1,
    }
    superuser_inspection = client.post(
        "/api/v1/timetable/legacy-projects/inspect",
        content=archive_bytes,
        headers={**headers["superuser"], "Content-Type": "application/octet-stream"},
    )
    assert superuser_inspection.status_code == 200
    for role in ("operator", "executive"):
        rejected = client.post(
            "/api/v1/timetable/legacy-projects/inspect",
            content=archive_bytes,
            headers={**headers[role], "Content-Type": "application/octet-stream"},
        )
        assert rejected.status_code == 403

    with SessionLocal() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "timetable.legacy_project.inspected"))
        assert event is not None
        assert "T1" not in event.details_json
        assert "S1" not in event.details_json
        assert "C1" not in event.details_json


def test_legacy_project_import_creates_audited_draft_and_rejects_duplicate(lesson_context, configured_legacy_key):
    client, headers, resources = lesson_context
    rule = client.post(
        "/api/v1/timetable/rules",
        json={
            "academic_year": "2026",
            "target_type": "CLASS",
            "target_id": resources["instructional_class_id"],
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
            "rule": {},
        },
        headers=headers["admin"],
    )
    assert rule.status_code == 201, rule.text
    values = sample_data()
    values["R04.bin"][0]["Length"] = 2
    values["R05.bin"][1]["DayOfWeek"] = "Mon"
    values["R05.bin"][1]["Period"] = 2
    archive = encrypted_archive(values)
    options = {
        "name": "Imported legacy week",
        "academic_year": "2026",
        "week_start": "2026-11-02",
        "teachers": {"0": resources["teacher_id"]},
        "subjects": {"0": resources["subject_id"]},
        "classes": {"0": resources["instructional_class_id"]},
    }
    import_envelope = json.dumps(options).encode() + b"\n" + archive
    response = client.post(
        "/api/v1/timetable/legacy-projects/import",
        content=import_envelope,
        headers={
            **headers["admin"],
            "Content-Type": "application/vnd.sps.legacy-pri-import",
        },
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert result["status"] == "DRAFT"
    assert result["placement_count"] == 1
    version = client.get(f"/api/v1/timetable/versions/{result['version_id']}", headers=headers["superuser"])
    assert version.status_code == 200
    assert len(version.json()["placements"]) == 1
    assert version.json()["placements"][0]["period_count"] == 2
    assert len(version.json()["placements"][0]["slots"]) == 2
    assert version.json()["pending"] == []
    duplicate = client.post(
        "/api/v1/timetable/legacy-projects/import",
        content=import_envelope,
        headers={
            **headers["admin"],
            "Content-Type": "application/vnd.sps.legacy-pri-import",
        },
    )
    assert duplicate.status_code == 409
    with SessionLocal() as db:
        event = db.scalar(select(AuditEvent).where(AuditEvent.action == "timetable.legacy_project.imported"))
        assert event is not None
        assert "source_sha256" in event.details_json
        assert "T1" not in event.details_json


def test_legacy_project_import_requires_explicit_mapping_and_it_role(lesson_context, configured_legacy_key):
    client, headers, resources = lesson_context
    archive = encrypted_archive()
    options = {
        "name": "Imported legacy week",
        "academic_year": "2026",
        "week_start": "2026-10-19",
        "teachers": {"0": resources["teacher_id"]},
        "subjects": {"0": resources["subject_id"]},
        "classes": {"0": resources["instructional_class_id"]},
    }
    request_headers = {
        "Content-Type": "application/vnd.sps.legacy-pri-import",
    }
    denied = client.post(
        "/api/v1/timetable/legacy-projects/import",
        content=json.dumps(options).encode() + b"\n" + archive,
        headers={**headers["operator"], **request_headers},
    )
    assert denied.status_code == 403
    missing = {**options, "teachers": {}}
    rejected = client.post(
        "/api/v1/timetable/legacy-projects/import",
        content=json.dumps(missing).encode() + b"\n" + archive,
        headers={**headers["admin"], **request_headers},
    )
    assert rejected.status_code == 422


def test_legacy_project_import_rejects_empty_schedule(lesson_context, configured_legacy_key):
    client, headers, resources = lesson_context
    values = sample_data()
    values["R04.bin"] = []
    values["R05.bin"] = []
    archive = encrypted_archive(values)
    options = {
        "name": "Empty legacy week",
        "academic_year": "2026",
        "week_start": "2026-10-26",
        "teachers": {"0": resources["teacher_id"]},
        "subjects": {"0": resources["subject_id"]},
        "classes": {"0": resources["instructional_class_id"]},
    }
    response = client.post(
        "/api/v1/timetable/legacy-projects/import",
        content=json.dumps(options).encode() + b"\n" + archive,
        headers={**headers["admin"], "Content-Type": "application/vnd.sps.legacy-pri-import"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Legacy project must contain classes, lesson requirements and placements"


def test_legacy_project_import_rolls_back_requirements_when_source_blocks_cannot_be_packed(lesson_context, configured_legacy_key):
    client, headers, resources = lesson_context
    rule = client.post(
        "/api/v1/timetable/rules",
        json={
            "academic_year": "2026",
            "target_type": "CLASS",
            "target_id": resources["instructional_class_id"],
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
            "rule": {},
        },
        headers=headers["admin"],
    )
    assert rule.status_code == 201, rule.text
    values = sample_data()
    values["R04.bin"][0]["Length"] = 2
    archive = encrypted_archive(values)
    options = {
        "name": "Rollback invalid imported week",
        "academic_year": "2026",
        "week_start": "2026-11-16",
        "teachers": {"0": resources["teacher_id"]},
        "subjects": {"0": resources["subject_id"]},
        "classes": {"0": resources["instructional_class_id"]},
    }
    response = client.post(
        "/api/v1/timetable/legacy-projects/import",
        content=json.dumps(options).encode() + b"\n" + archive,
        headers={**headers["admin"], "Content-Type": "application/vnd.sps.legacy-pri-import"},
    )

    assert response.status_code == 422
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(LessonRequirement.id).where(
                    LessonRequirement.academic_year == options["academic_year"],
                    LessonRequirement.instructional_class_id == resources["instructional_class_id"],
                    LessonRequirement.teacher_id == resources["teacher_id"],
                    LessonRequirement.subject_id == resources["subject_id"],
                )
            )
            is None
        )
        assert db.scalar(select(TimetableVersion.id).where(TimetableVersion.name == options["name"])) is None


def test_legacy_project_preflight_requires_key_and_bounds_upload(lesson_context, monkeypatch):
    client, headers, _ = lesson_context
    monkeypatch.setenv("LEGACY_PRI_KEY_HEX", "")
    get_settings.cache_clear()
    try:
        unavailable = client.post(
            "/api/v1/timetable/legacy-projects/validate",
            content=b"test",
            headers={**headers["admin"], "Content-Type": "application/octet-stream"},
        )
        assert unavailable.status_code == 503
        oversized = client.post(
            "/api/v1/timetable/legacy-projects/validate",
            content=b"x" * (10 * 1024 * 1024 + 1),
            headers={
                **headers["admin"],
                "Content-Type": "application/octet-stream",
            },
        )
        assert oversized.status_code == 413
    finally:
        get_settings.cache_clear()


def test_legacy_project_preflight_bounds_rows_before_reconciliation(lesson_context, configured_legacy_key):
    client, headers, _ = lesson_context
    values = sample_data()
    values["R01.bin"] = [
        {"Id": index, "Name": f"Teacher {index}", "Availability": ":".join(["1"] * 20)}
        for index in range(MAX_LEGACY_SOURCE_ROWS + 1)
    ]
    archive = encrypted_archive(values)
    response = client.post(
        "/api/v1/timetable/legacy-projects/validate",
        content=archive,
        headers={**headers["admin"], "Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 413
    assert response.json()["detail"] == "Legacy project exceeds the source row limit"
    options = {
        "name": "Oversized legacy import",
        "academic_year": "2026",
        "week_start": "2026-11-16",
        "teachers": {},
        "subjects": {},
        "classes": {},
    }
    imported = client.post(
        "/api/v1/timetable/legacy-projects/import",
        content=json.dumps(options).encode() + b"\n" + archive,
        headers={**headers["admin"], "Content-Type": "application/vnd.sps.legacy-pri-import"},
    )
    assert imported.status_code == 413
    assert imported.json()["detail"] == "Legacy project exceeds the source row limit"
