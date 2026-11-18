"""Read-only parser and reconciliation checks for legacy TImeTables .pri files.

The legacy format is a ZIP of AES-CBC encrypted JSON. This module intentionally
does not deserialize .NET BinaryFormatter payloads and never writes to the input.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MEMBERS = {f"R{i:02}.bin" for i in range(1, 7)}
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_TOTAL_UNCOMPRESSED_BYTES = 32 * 1024 * 1024
LEGACY_DAYS = {"mo", "tu", "we", "th", "fr", "mon", "tue", "wed", "thu", "fri"}
LEGACY_AVAILABILITY_DAYS = ("MON", "TUE", "WED", "THU", "FRI")
LEGACY_AVAILABILITY_PERIODS = ("P1", "P2", "P3", "P4")
LEGACY_PERIOD_MAP = {1: "P1", 2: "P2", 3: "LUNCH", 4: "P3", 5: "P4"}
LEGACY_LUNCH_PERIOD = 3


class LegacyPriError(ValueError):
    """The .pri archive is invalid or cannot be safely interpreted."""


def map_legacy_availability(value: str) -> dict[str, list[str]] | None:
    """Translate the legacy UI's 20 day-major checkboxes into current slots.

    The 25-flag shape appears in saved files but has no verified meaning in the
    legacy UI, so it must be reconciled manually instead of guessed.
    """
    flags = value.split(":") if isinstance(value, str) else []
    if len(flags) != len(LEGACY_AVAILABILITY_DAYS) * len(LEGACY_AVAILABILITY_PERIODS) or any(flag not in {"0", "1"} for flag in flags):
        return None
    return {
        day: [period for period_index, period in enumerate(LEGACY_AVAILABILITY_PERIODS) if flags[day_index * 4 + period_index] == "1"]
        for day_index, day in enumerate(LEGACY_AVAILABILITY_DAYS)
    }


@dataclass(frozen=True)
class LegacyPriData:
    teachers: list[dict[str, Any]]
    subjects: list[dict[str, Any]]
    classes: list[dict[str, Any]]
    lessons: list[dict[str, Any]]
    placements: list[dict[str, Any]]
    pending: list[dict[str, Any]]


def _decrypt_member(data: bytes, key: bytes, name: str) -> Any:
    if len(data) < 32 or len(data) > MAX_MEMBER_BYTES:
        raise LegacyPriError(f"{name} has an invalid encrypted payload size")
    iv, ciphertext = data[:16], data[16:]
    if len(ciphertext) % 16:
        raise LegacyPriError(f"{name} has a malformed AES payload")
    decryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(algorithms.AES.block_size).unpadder()
    try:
        plaintext = unpadder.update(padded) + unpadder.finalize()
        value = json.loads(plaintext.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LegacyPriError(f"{name} failed decryption or JSON validation") from exc
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise LegacyPriError(f"{name} must contain a JSON array of objects")
    return value


def read_legacy_pri(path: str | Path, key: bytes) -> LegacyPriData:
    """Read the six known members, with archive bounds and exact-name checks."""
    source = Path(path)
    try:
        if source.stat().st_size > MAX_ARCHIVE_BYTES:
            raise LegacyPriError(".pri archive exceeds the size limit")
        archive_bytes = source.read_bytes()
    except OSError as exc:
        raise LegacyPriError("Unable to read the .pri archive") from exc
    return read_legacy_pri_bytes(archive_bytes, key)


def read_legacy_pri_bytes(archive_bytes: bytes, key: bytes) -> LegacyPriData:
    """Read a bounded archive from memory, without writing upload bytes to disk."""
    if len(key) not in (16, 24, 32):
        raise LegacyPriError("AES key must be 16, 24 or 32 bytes")
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        raise LegacyPriError(".pri archive exceeds the size limit")
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            if len(names) != len(set(names)):
                raise LegacyPriError(".pri archive contains duplicate member names")
            if set(names) != MEMBERS or any(entry.is_dir() for entry in entries):
                raise LegacyPriError(".pri archive must contain exactly R01.bin through R06.bin")
            if sum(entry.file_size for entry in entries) > MAX_TOTAL_UNCOMPRESSED_BYTES:
                raise LegacyPriError(".pri archive expands beyond the size limit")
            if any(entry.file_size > MAX_MEMBER_BYTES for entry in entries):
                raise LegacyPriError(".pri member exceeds the size limit")
            payloads = {entry.filename: _decrypt_member(archive.read(entry), key, entry.filename) for entry in entries}
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise LegacyPriError("Unable to read the .pri archive") from exc
    return LegacyPriData(
        teachers=payloads["R01.bin"],
        subjects=payloads["R02.bin"],
        classes=payloads["R03.bin"],
        lessons=payloads["R04.bin"],
        placements=payloads["R05.bin"],
        pending=payloads["R06.bin"],
    )


def reconcile_legacy_pri(data: LegacyPriData) -> dict[str, Any]:
    """Return counts and row-indexed issues without exposing names or values."""
    issues: list[dict[str, Any]] = []

    def add_issue(code: str, source: str, *, row: int | None = None, count: int | None = None) -> None:
        issue: dict[str, Any] = {"code": code, "source": source}
        if row is not None:
            issue["row"] = row
        if count is not None:
            issue["count"] = count
        issues.append(issue)

    availability_mapping: Counter[str] = Counter()
    catalogs = {
        "teacher": (data.teachers, "Name"),
        "subject": (data.subjects, "Name"),
        "class": (data.classes, "Name"),
    }
    indexes: dict[str, set[str]] = {}
    for kind, (rows, field) in catalogs.items():
        indexes[kind] = set()
        seen: set[str] = set()
        for row_index, row in enumerate(rows):
            value = row.get(field)
            if not isinstance(value, str) or not value.strip():
                add_issue(f"missing_{kind}_name", kind, row=row_index)
                continue
            normalized = value.strip().casefold()
            if normalized in seen:
                add_issue(f"duplicate_{kind}_name", kind, row=row_index)
            seen.add(normalized)
            indexes[kind].add(value.strip())
            if kind == "teacher":
                availability = row.get("Availability", "")
                slots = availability.split(":") if isinstance(availability, str) else []
                if map_legacy_availability(availability) is not None:
                    availability_mapping["20_teaching_slot_profiles"] += 1
                elif len(slots) == 25 and all(slot in {"0", "1"} for slot in slots):
                    availability_mapping["25_period_position_profiles"] += 1
                    add_issue("legacy_availability_mapping_required", kind, row=row_index)
                else:
                    add_issue("invalid_teacher_availability", kind, row=row_index)

    requirements: Counter[tuple[str, str, str]] = Counter()
    requirement_rows: dict[tuple[str, str, str], list[int]] = {}
    for row_index, row in enumerate(data.lessons):
        references = {kind: row.get(field) for kind, field in (("teacher", "Teacher"), ("subject", "Subject"), ("class", "InstClass"))}
        for kind, value in references.items():
            if kind == "teacher" and (not isinstance(value, str) or not value.strip()):
                add_issue("missing_teacher_reference", "lesson_requirement", row=row_index)
                continue
            is_known_composite = (
                kind == "teacher" and isinstance(value, str) and all(part.strip() in indexes[kind] for part in value.split("/"))
            )
            if value == "ALL" and kind == "teacher":
                continue
            if not isinstance(value, str) or (value not in indexes[kind] and not is_known_composite):
                add_issue(f"invalid_{kind}_reference", "lesson_requirement", row=row_index)
        count, length = row.get("Count"), row.get("Length")
        if type(count) is not int or count < 1 or type(length) is not int or length < 1:
            add_issue("invalid_lesson_count_or_length", "lesson_requirement", row=row_index)
        teacher_ref = references["teacher"]
        if isinstance(teacher_ref, str) and teacher_ref != "ALL":
            components = [part.strip() for part in teacher_ref.split("/")]
            if len(components) > 1:
                if not all(part in indexes["teacher"] for part in components):
                    add_issue("invalid_composite_teacher_reference", "lesson_requirement", row=row_index)
                add_issue("composite_teacher_mapping_required", "lesson_requirement", row=row_index)
        if all(isinstance(value, str) for value in references.values()):
            resource_tuple = (references["class"], str(teacher_ref), references["subject"])
            requirements[resource_tuple] += count if isinstance(count, int) else 0
            requirement_rows.setdefault(resource_tuple, []).append(row_index)

    occupied_classes: set[tuple[str, str, int]] = set()
    occupied_teachers: set[tuple[str, str, int]] = set()
    placed: Counter[tuple[str, str, str]] = Counter()
    for row_index, row in enumerate(data.placements):
        class_name, day, period = row.get("InstClass"), row.get("DayOfWeek"), row.get("Period")
        teacher, subject = row.get("Teacher"), row.get("Subject")
        is_lunch_slot = type(period) is int and period == LEGACY_LUNCH_PERIOD
        for kind, value in (("class", class_name), ("teacher", teacher), ("subject", subject)):
            if kind == "teacher" and value == "ALL":
                continue
            if kind == "teacher" and (not isinstance(value, str) or not value.strip()):
                if not is_lunch_slot:
                    add_issue("missing_placement_teacher", "placement", row=row_index)
                continue
            if not isinstance(value, str) or (
                value not in indexes[kind] and not (kind == "teacher" and all(part.strip() in indexes[kind] for part in value.split("/")))
            ):
                add_issue(f"invalid_placement_{kind}_reference", "placement", row=row_index)
        if type(period) is not int or not 1 <= period <= 5 or not isinstance(day, str) or day.casefold() not in LEGACY_DAYS:
            add_issue("invalid_placement_slot", "placement", row=row_index)
            continue
        if is_lunch_slot:
            has_assigned_teacher = isinstance(teacher, str) and teacher.strip() and teacher != "ALL"
            code = "lesson_in_lunch_slot" if has_assigned_teacher else "lunch_entry_requires_review"
            add_issue(code, "placement", row=row_index)
            if teacher == "ALL":
                add_issue("whole_school_event_mapping_required", "placement", row=row_index)
            continue
        slot = (str(class_name), day.casefold(), period)
        if slot in occupied_classes:
            add_issue("duplicate_class_slot", "placement", row=row_index)
        occupied_classes.add(slot)
        teacher_components = (
            [part.strip() for part in teacher.split("/") if part.strip() in indexes["teacher"]] if isinstance(teacher, str) else []
        )
        if teacher == "ALL":
            add_issue("whole_school_event_mapping_required", "placement", row=row_index)
        else:
            if len(teacher_components) > 1:
                add_issue("composite_teacher_mapping_required", "placement", row=row_index)
            for component in teacher_components:
                teacher_slot = (component, day.casefold(), period)
                if teacher_slot in occupied_teachers:
                    add_issue("duplicate_teacher_slot", "placement", row=row_index)
                occupied_teachers.add(teacher_slot)
        if all(isinstance(value, str) for value in (class_name, teacher, subject)) and teacher != "ALL":
            placed[(class_name, teacher, subject)] += 1

    for resource_tuple, expected in requirements.items():
        actual = placed[resource_tuple]
        if actual < expected:
            issue = {
                "code": "unplaced_lesson_periods",
                "source": "lesson_requirement",
                "rows": requirement_rows[resource_tuple],
                "count": expected - actual,
            }
            issues.append(issue)
        elif actual > expected:
            issue = {
                "code": "overplaced_lesson_periods",
                "source": "lesson_requirement",
                "rows": requirement_rows[resource_tuple],
                "count": actual - expected,
            }
            issues.append(issue)
    for resource_tuple, actual in placed.items():
        if resource_tuple not in requirements:
            add_issue("placement_without_lesson_requirement", "placement", count=actual)

    codes = Counter(issue["code"] for issue in issues)
    return {
        "counts": {
            "teachers": len(data.teachers),
            "subjects": len(data.subjects),
            "classes": len(data.classes),
            "lesson_requirements": len(data.lessons),
            "placements": len(data.placements),
            "pending_lessons": len(data.pending),
        },
        "period_mapping": {str(period): display for period, display in LEGACY_PERIOD_MAP.items()},
        "availability_profiles": dict(sorted(availability_mapping.items())),
        "issue_counts": dict(sorted(codes.items())),
        "issues": issues,
        "valid": not issues,
        "import_ready": not issues,
    }
