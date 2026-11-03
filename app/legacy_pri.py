"""Read-only parser and reconciliation checks for legacy TImeTables .pri files.

The legacy format is a ZIP of AES-CBC encrypted JSON. This module intentionally
does not deserialize .NET BinaryFormatter payloads and never writes to the input.
"""

from __future__ import annotations

import io
import json
import zipfile
import zlib
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


class LegacyPriError(ValueError):
    """The .pri archive is invalid or cannot be safely interpreted."""


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


def read_legacy_pri(source: str | Path | bytes, key: bytes) -> LegacyPriData:
    """Read the six known members, with archive bounds and exact-name checks."""
    if len(key) not in (16, 24, 32):
        raise LegacyPriError("AES key must be 16, 24 or 32 bytes")
    try:
        if isinstance(source, bytes):
            archive_bytes = source
        else:
            source_path = Path(source)
            if source_path.stat().st_size > MAX_ARCHIVE_BYTES:
                raise LegacyPriError(".pri archive exceeds the size limit")
            archive_bytes = source_path.read_bytes()
        if len(archive_bytes) > MAX_ARCHIVE_BYTES:
            raise LegacyPriError(".pri archive exceeds the size limit")
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
    except (OSError, zipfile.BadZipFile, zipfile.LargeZipFile, RuntimeError, EOFError, NotImplementedError, zlib.error) as exc:
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
                issues.append({"code": f"missing_{kind}_name", "row": row_index})
                continue
            normalized = value.strip().casefold()
            if normalized in seen:
                issues.append({"code": f"duplicate_{kind}_name", "row": row_index})
            seen.add(normalized)
            indexes[kind].add(value.strip())
            if kind == "teacher":
                availability = row.get("Availability", "")
                slots = availability.split(":") if isinstance(availability, str) else []
                if len(slots) != 25 or any(slot not in {"0", "1"} for slot in slots):
                    issues.append({"code": "invalid_teacher_availability", "row": row_index})

    requirements: Counter[tuple[str, str, str]] = Counter()
    for row_index, row in enumerate(data.lessons):
        references = {kind: row.get(field) for kind, field in (("teacher", "Teacher"), ("subject", "Subject"), ("class", "InstClass"))}
        for kind, value in references.items():
            if kind == "teacher" and (not isinstance(value, str) or not value.strip()):
                issues.append({"code": "missing_teacher_reference", "row": row_index})
                continue
            is_known_composite = (
                kind == "teacher" and isinstance(value, str) and all(part.strip() in indexes[kind] for part in value.split("/"))
            )
            if value == "ALL" and kind == "teacher":
                continue
            if not isinstance(value, str) or (value not in indexes[kind] and not is_known_composite):
                issues.append({"code": f"invalid_{kind}_reference", "row": row_index})
        count, length = row.get("Count"), row.get("Length")
        if type(count) is not int or count < 1 or type(length) is not int or length < 1:
            issues.append({"code": "invalid_lesson_count_or_length", "row": row_index})
        teacher_ref = references["teacher"]
        if isinstance(teacher_ref, str) and teacher_ref != "ALL":
            components = [part.strip() for part in teacher_ref.split("/")]
            if len(components) > 1:
                if not all(part in indexes["teacher"] for part in components):
                    issues.append({"code": "invalid_composite_teacher_reference", "row": row_index})
                issues.append({"code": "composite_teacher_mapping_required", "row": row_index})
        if all(isinstance(value, str) for value in references.values()):
            requirements[(references["class"], str(teacher_ref), references["subject"])] += count if isinstance(count, int) else 0

    occupied_classes: set[tuple[str, str, int]] = set()
    occupied_teachers: set[tuple[str, str, int]] = set()
    placed: Counter[tuple[str, str, str]] = Counter()
    for row_index, row in enumerate(data.placements):
        class_name, day, period = row.get("InstClass"), row.get("DayOfWeek"), row.get("Period")
        teacher, subject = row.get("Teacher"), row.get("Subject")
        for kind, value in (("class", class_name), ("teacher", teacher), ("subject", subject)):
            if kind == "teacher" and value == "ALL":
                continue
            if kind == "teacher" and (not isinstance(value, str) or not value.strip()):
                issues.append({"code": "missing_placement_teacher", "row": row_index})
                continue
            if not isinstance(value, str) or (
                value not in indexes[kind] and not (kind == "teacher" and all(part.strip() in indexes[kind] for part in value.split("/")))
            ):
                issues.append({"code": f"invalid_placement_{kind}_reference", "row": row_index})
        if type(period) is not int or not 1 <= period <= 5 or not isinstance(day, str) or day.casefold() not in LEGACY_DAYS:
            issues.append({"code": "invalid_placement_slot", "row": row_index})
            continue
        slot = (str(class_name), day.casefold(), period)
        if slot in occupied_classes:
            issues.append({"code": "duplicate_class_slot", "row": row_index})
        occupied_classes.add(slot)
        teacher_components = (
            [part.strip() for part in teacher.split("/") if part.strip() in indexes["teacher"]] if isinstance(teacher, str) else []
        )
        if teacher == "ALL":
            issues.append({"code": "whole_school_event_mapping_required", "row": row_index})
        else:
            if len(teacher_components) > 1:
                issues.append({"code": "composite_teacher_mapping_required", "row": row_index})
            for component in teacher_components:
                teacher_slot = (component, day.casefold(), period)
                if teacher_slot in occupied_teachers:
                    issues.append({"code": "duplicate_teacher_slot", "row": row_index})
                occupied_teachers.add(teacher_slot)
        if all(isinstance(value, str) for value in (class_name, teacher, subject)) and teacher != "ALL":
            placed[(class_name, teacher, subject)] += 1

    for resource_tuple, expected in requirements.items():
        actual = placed[resource_tuple]
        if actual < expected:
            issues.append({"code": "unplaced_lesson_periods", "count": expected - actual})
        elif actual > expected:
            issues.append({"code": "overplaced_lesson_periods", "count": actual - expected})
    for resource_tuple, actual in placed.items():
        if resource_tuple not in requirements:
            issues.append({"code": "placement_without_lesson_requirement", "count": actual})

    if data.teachers or data.placements:
        issues.append(
            {
                "code": "legacy_period_mapping_required",
                "count": len(data.placements),
                "availability_vectors": len(data.teachers),
            }
        )

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
        "issue_counts": dict(sorted(codes.items())),
        "issues": issues,
        "valid": not issues,
        "import_ready": not issues,
    }
