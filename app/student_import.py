"""Bounded, non-mutating parser for supported Student Intake 2021/2023 workbooks."""

from __future__ import annotations

import logging
import zipfile
from datetime import date, datetime
from io import BytesIO
from typing import Any

from openpyxl import load_workbook
from pydantic import ValidationError

from app.schemas import StudentCreate
from app.student_class_mapping import STUDENT_INTAKE_2021, STUDENT_INTAKE_2023

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ROWS = 10_000
MAX_COLUMNS = 64
MAX_ZIP_ENTRIES = 2_000
MAX_ZIP_MEMBER_BYTES = 50 * 1024 * 1024
MAX_ZIP_TOTAL_BYTES = 100 * 1024 * 1024
SHEET_NAMES = {STUDENT_INTAKE_2021: "Student Intake 2021", STUDENT_INTAKE_2023: "Student Intake 2023"}
logger = logging.getLogger(__name__)


class ImportFileError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _header_key(value: Any) -> str:
    return " ".join(str(value or "").replace("\u00a0", " ").split()).upper()


HEADER_FIELDS_2023 = {
    "PRIS NO.": "pris_no",
    "CAT": "category",
    "EDR/ROS": "edr_ros",
    "IC": "ic_number",
    "NAME": "name",
    "INSTN CLASS": "class_name",
    "STATUS": "status",
    "STATUS EFFECTIVE": "status_effective",
    "ADM TYPE": "admission_type",
    "EXAM LEVEL": "exam_level",
    "DOB": "date_of_birth",
    "AGE IN AY'23": "age_in_academic_year",
    "GENDER": "gender",
    "LANG 1 (GP/EL)": "language_1",
    "LANG 2 (MT)": "language_2",
    "MATH 1 (MA / H2 MATH)": "math_1",
    "MATH 2 (A MA / H1 MATH)": "math_2",
    "CPA": "cpa",
    "SCI (PHY,BIO)": "science",
    "HUM (SS,GEO)": "humanities",
    "COM 1 (POA)": "commerce_1",
    "COM 2 (MOB/BS)": "commerce_2",
    "COM 3 (ECONS)": "commerce_3",
    "AA": "aa",
    "NATIONALITY": "nationality",
    "CITIZENSHIP": "citizenship",
    "BIRTHPLACE": "birthplace",
    "RELIGION": "religion",
    "RACE": "race",
    "MARITAL STATUS": "marital_status",
    "MCH / NOK NAME": "next_of_kin_name",
    "MCH / NOK NRIC": "next_of_kin_nric",
    "MCH / NOK RELATIONSHIP": "next_of_kin_relationship",
    "MCH / NOK CONTACT NUMBER": "next_of_kin_contact",
    "MCH / NOK ADDRESS (PORTS)": "next_of_kin_address_ports",
    "MCH / NOK ADDRESS (FROM STUDENT)": "next_of_kin_address_from_student",
    "MCH / NOK CONTACT NUMBER (FROM STUDENT)": "student_contact",
}
HEADER_FIELDS_2023 = {_header_key(key): value for key, value in HEADER_FIELDS_2023.items()}
HEADER_FIELDS_2021 = {
    "PRIS NO": "pris_no",
    "CAT": "category",
    "EDR/ROS": "edr_ros",
    "VERIFY": "verification_note",
    "IC": "ic_number",
    "NAME": "name",
    "CLASS": "class_name",
    "STATUS": "status",
    "STATUS EFFECTIVE": "status_effective",
    "ADM TYPE": "admission_type",
    "EXAM LEVEL": "exam_level",
    "DOB": "date_of_birth",
    "AGE IN AY'21": "age_in_academic_year",
    "GENDER": "gender",
    "LANG 1": "language_1",
    "LANG 2": "language_2",
    "MATH 1": "math_1",
    "MATH 2": "math_2",
    "SCI": "science",
    "HUM": "humanities",
    "COM 1": "commerce_1",
    "COM 2": "commerce_2",
    "COM 3": "commerce_3",
    "ELECTIVE": "elective",
    "AA": "aa",
    "NATIONALITY": "nationality",
    "BIRTHPLACE": "birthplace",
    "RELIGION": "religion",
    "RACE": "race",
    "MARITAL STATUS": "marital_status",
    "MCH / NOK NAME": "next_of_kin_name",
    "MCH / NOK NRIC": "next_of_kin_nric",
    "MCH / NOK RELATIONSHIP": "next_of_kin_relationship",
    "MCH / NOK CONTACT NUMBER": "next_of_kin_contact",
    "MCH / NOK ADDRESS (PORTS)": "next_of_kin_address_ports",
    "MCH / NOK ADDRESS (FROM STUDENT)": "next_of_kin_address_from_student",
}
HEADER_FIELDS_2021 = {_header_key(key): value for key, value in HEADER_FIELDS_2021.items()}
HEADER_FIELDS_BY_SOURCE = {STUDENT_INTAKE_2021: HEADER_FIELDS_2021, STUDENT_INTAKE_2023: HEADER_FIELDS_2023}
ACADEMIC_YEAR_BY_SOURCE = {STUDENT_INTAKE_2021: "2021", STUDENT_INTAKE_2023: "2023"}
REQUIRED_HEADERS = {"pris_no", "name", "class_name", "category", "status"}
ROW_IDENTIFIER_FIELDS = {"pris_no"}
CREATE_REQUIRED_FIELDS = ("name", "class_name", "category", "status")
TEXT_ONLY_IDENTIFIERS = {"pris_no", "ic_number", "next_of_kin_nric", "next_of_kin_contact", "student_contact"}


def _validate_archive(data: bytes) -> None:
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImportFileError("file_too_large")
    stream = BytesIO(data)
    if not zipfile.is_zipfile(stream):
        raise ImportFileError("invalid_xlsx")
    try:
        with zipfile.ZipFile(stream) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ZIP_ENTRIES:
                raise ImportFileError("invalid_xlsx")
            total = 0
            names = set()
            for entry in entries:
                name = entry.filename.replace("\\", "/")
                if name.startswith("/") or ".." in name.split("/") or entry.flag_bits & 1:
                    raise ImportFileError("invalid_xlsx")
                if name in names:
                    raise ImportFileError("invalid_xlsx")
                names.add(name)
                total += entry.file_size
                if entry.file_size > MAX_ZIP_MEMBER_BYTES or total > MAX_ZIP_TOTAL_BYTES:
                    raise ImportFileError("invalid_xlsx")
                if name.startswith("xl/externalLinks/") or name.endswith("vbaProject.bin"):
                    raise ImportFileError("invalid_xlsx")
            if not {"[Content_Types].xml", "xl/workbook.xml"}.issubset(names):
                raise ImportFileError("invalid_xlsx")
            if archive.testzip() is not None:
                raise ImportFileError("invalid_xlsx")
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ImportFileError("invalid_xlsx") from exc


def _cell_text(value: Any, field: str, warnings: list[dict[str, str]]) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("invalid_value")
    if isinstance(value, int | float):
        if field in TEXT_ONLY_IDENTIFIERS:
            if field == "pris_no":
                raise ValueError("identifier_must_be_text")
            if isinstance(value, float) and not value.is_integer():
                raise ValueError("numeric_identifier_must_be_integer")
            if value < 0:
                raise ValueError("numeric_identifier_must_be_nonnegative")
            warnings.append({"field": field, "code": "numeric_cell_may_lose_leading_zeros"})
        if isinstance(value, float) and value.is_integer():
            value = int(value)
    text = str(value).strip()
    return text or None


def _date_text(value: Any) -> str | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    for pattern in ("%d/%m/%Y", "%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(text, pattern).date().isoformat()
        except ValueError:
            pass
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError as exc:
        raise ValueError("invalid_date") from exc


def _age(value: Any) -> int | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        raise ValueError("invalid_integer")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_integer") from exc
    if str(value).strip() not in {str(number), f"{number}.0"}:
        raise ValueError("invalid_integer")
    if not 0 <= number <= 120:
        raise ValueError("out_of_range")
    return number


def _row_fields(values: dict[str, Any], academic_year: str) -> tuple[dict[str, Any], list[dict[str, str]], list[dict[str, str]]]:
    fields: dict[str, Any] = {}
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for field, value in values.items():
        try:
            if field in {"date_of_birth", "status_effective"}:
                fields[field] = _date_text(value)
            elif field == "age_in_academic_year":
                fields[field] = _age(value)
            else:
                fields[field] = _cell_text(value, field, warnings)
        except ValueError as exc:
            errors.append({"field": field, "code": str(exc)})
    if fields.get("age_in_academic_year") is not None:
        fields["academic_year"] = academic_year
    for required in ROW_IDENTIFIER_FIELDS:
        if fields.get(required) is None:
            errors.append({"field": required, "code": "required"})
    if errors:
        return fields, errors, warnings
    missing_create_fields = {field for field in CREATE_REQUIRED_FIELDS if fields.get(field) is None}
    validation_fields = fields.copy()
    for field in missing_create_fields:
        validation_fields[field] = {
            "name": "Validation placeholder",
            "class_name": "Validation class",
            "category": "OP",
            "status": "ACTIVE",
        }[field]
    try:
        payload = StudentCreate.model_validate(validation_fields)
    except ValidationError as exc:
        for detail in exc.errors(include_input=False):
            location = str(detail["loc"][0]) if detail.get("loc") else "row"
            errors.append({"field": location, "code": "invalid_value"})
        return fields, errors, warnings
    normalized = payload.model_dump(mode="json")
    for field in missing_create_fields:
        normalized[field] = None
    return normalized, [], warnings


def parse_student_workbook(data: bytes, source_workbook: str = STUDENT_INTAKE_2023) -> list[dict[str, Any]]:
    _validate_archive(data)
    if source_workbook not in SHEET_NAMES:
        raise ImportFileError("unsupported_workbook")
    workbook = None
    cached_workbook = None
    try:
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=False, keep_links=False)
        cached_workbook = load_workbook(BytesIO(data), read_only=True, data_only=True, keep_links=False)
        sheet_name = SHEET_NAMES[source_workbook]
        if sheet_name not in workbook.sheetnames:
            raise ImportFileError("required_worksheet_missing")
        sheet = workbook[sheet_name]
        # The supported 2021 worksheet is hidden in the supplied source workbook.
        # Import only the exact sheet selected by the Operator and this version's map.
        cached_sheet = cached_workbook[sheet_name]
        if not sheet.max_row or sheet.max_row < 2 or sheet.max_row > MAX_ROWS + 1:
            raise ImportFileError("row_limit_or_empty")
        if not sheet.max_column or sheet.max_column > MAX_COLUMNS:
            raise ImportFileError("column_limit")
        header = next(sheet.iter_rows(min_row=1, max_row=1, max_col=sheet.max_column))
        positions: dict[int, str] = {}
        seen: set[str] = set()
        unknown: list[str] = []
        for index, cell in enumerate(header):
            key = _header_key(cell.value)
            if not key:
                continue
            if key == "S/N":
                continue
            field = HEADER_FIELDS_BY_SOURCE[source_workbook].get(key)
            if field is None:
                unknown.append("unknown")
                continue
            if field in seen:
                raise ImportFileError("duplicate_header")
            seen.add(field)
            positions[index] = field
        if unknown:
            raise ImportFileError("unsupported_header")
        if not REQUIRED_HEADERS.issubset(seen):
            raise ImportFileError("required_header_missing")
        records: list[dict[str, Any]] = []
        cached_rows = iter(cached_sheet.iter_rows(min_row=2, max_col=sheet.max_column))
        for row_number, row in enumerate(sheet.iter_rows(min_row=2, max_col=sheet.max_column), start=2):
            cached_row = next(cached_rows)
            if all(cell.value is None or (isinstance(cell.value, str) and not cell.value.strip()) for cell in row):
                continue
            values = {field: row[index].value for index, field in positions.items()}
            formula_errors = []
            for column_index, cell in enumerate(row):
                field = positions.get(column_index)
                data_type = getattr(cell, "data_type", None)
                if data_type == "e":
                    if field:
                        values[field] = None
                    formula_errors.append({"field": field or "row", "code": "excel_error_value"})
                    continue
                if data_type != "f":
                    continue
                if field == "age_in_academic_year":
                    cached_value = cached_row[cell.column - 1].value
                    if cached_value is None:
                        formula_errors.append({"field": field, "code": "formula_value_missing"})
                    else:
                        values[field] = cached_value
                else:
                    formula_errors.append({"field": field or "row", "code": "formula_not_allowed"})
            fields, errors, warnings = _row_fields(values, ACADEMIC_YEAR_BY_SOURCE[source_workbook])
            errors.extend(formula_errors)
            records.append({"row_number": row_number, "fields": fields, "errors": errors, "warnings": warnings})
        if not records:
            raise ImportFileError("no_student_rows")
        return records
    except ImportFileError:
        raise
    except Exception as exc:
        # Never propagate parser exceptions: they can contain workbook data or paths.
        logger.warning("Student workbook parser failed with %s", type(exc).__name__)
        raise ImportFileError("invalid_xlsx") from exc
    finally:
        if workbook is not None:
            workbook.close()
        if cached_workbook is not None:
            cached_workbook.close()


def mark_duplicate_identifiers(records: list[dict[str, Any]]) -> None:
    identifiers: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        pris_no = record["fields"].get("pris_no")
        if pris_no:
            identifiers.setdefault(str(pris_no).strip().upper(), []).append(record)
    for matches in identifiers.values():
        if len(matches) > 1:
            for record in matches:
                record["errors"].append({"field": "pris_no", "code": "duplicate_in_workbook"})
