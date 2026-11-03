import json
import zipfile

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.legacy_pri import LegacyPriError, read_legacy_pri, reconcile_legacy_pri

KEY = bytes(range(16))


def encrypted_member(value):
    iv = bytes(range(16, 32))
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(json.dumps(value).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(KEY), modes.CBC(iv)).encryptor()
    return iv + encryptor.update(padded) + encryptor.finalize()


def sample_data():
    return {
        "R01.bin": [{"Id": 0, "Name": "T1", "Availability": ":".join(["1"] * 25)}],
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
    values = members or sample_data()
    with zipfile.ZipFile(path, "w") as archive:
        for name, value in values.items():
            archive.writestr(name, encrypted_member(value))


def test_reads_exact_encrypted_json_members_without_mutating_source(tmp_path):
    source = tmp_path / "sample.pri"
    write_pri(source)
    before = source.read_bytes()
    data = read_legacy_pri(source, KEY)
    report = reconcile_legacy_pri(data)
    assert report["valid"] is False
    assert report["import_ready"] is False
    assert "legacy_period_mapping_required" in report["issue_counts"]
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
