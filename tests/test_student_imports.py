import json
import xml.etree.ElementTree as ET
import zipfile
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import pytest
from openpyxl import Workbook
from sqlalchemy import func, select

from app.crypto import decrypt_sensitive, decrypt_sensitive_bytes, encrypt_sensitive
from app.db import SessionLocal
from app.models import AuditEvent, Student, StudentImportBatch, StudentStatusHistory

BASE = "/api/v1/student-imports"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HEADERS = [
    "S/N",
    "Pris No.",
    "CAT",
    "EDR/ROS",
    "IC",
    "NAME",
    "INSTN CLASS",
    "STATUS",
    "STATUS EFFECTIVE",
    "ADM TYPE",
    "EXAM LEVEL",
    "DOB",
    "AGE IN AY'23",
    "GENDER",
    "LANG 1\n(GP/EL)",
    "LANG 2\n(MT)",
    "MATH 1\n(MA / H2 MATH)",
    "MATH 2\n(A MA / H1 MATH)",
    "CPA",
    "SCI\n(PHY,BIO)",
    "HUM\n(SS,GEO)",
    "COM 1\n(POA)",
    "COM 2\n(MOB/BS)",
    "COM 3\n(ECONS)",
    "AA",
    "NATIONALITY",
    "CITIZENSHIP",
    "BIRTHPLACE",
    "RELIGION",
    "RACE",
    "MARITAL STATUS",
    "MCH / NOK NAME",
    "MCH / NOK NRIC",
    "MCH / NOK RELATIONSHIP",
    "MCH / NOK CONTACT NUMBER",
    "MCH / NOK ADDRESS (PORTS)",
    "MCH / NOK ADDRESS (From Student)",
    "MCH / NOK CONTACT NUMBER (From Student)",
]
PROFILE_FIELDS = [
    "pris_no",
    "category",
    "edr_ros",
    "ic_number",
    "name",
    "class_name",
    "status",
    "status_effective",
    "admission_type",
    "exam_level",
    "date_of_birth",
    "age_in_academic_year",
    "gender",
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
    "nationality",
    "citizenship",
    "birthplace",
    "religion",
    "race",
    "marital_status",
    "next_of_kin_name",
    "next_of_kin_nric",
    "next_of_kin_relationship",
    "next_of_kin_contact",
    "next_of_kin_address_ports",
    "next_of_kin_address_from_student",
    "student_contact",
]
HEADERS_2021 = [
    "S/N",
    "PRIS NO",
    "CAT",
    "EDR/ROS",
    "VERIFY",
    "IC",
    "NAME",
    "CLASS",
    "STATUS",
    "STATUS EFFECTIVE",
    "ADM TYPE",
    "EXAM LEVEL",
    "DOB",
    "AGE IN AY'21",
    "GENDER",
    "LANG 1",
    "LANG 2",
    "MATH 1",
    "MATH 2",
    "SCI",
    "HUM",
    "COM 1",
    "COM 2",
    "COM 3",
    "ELECTIVE",
    "AA",
    "NATIONALITY",
    "BIRTHPLACE",
    "RELIGION",
    "RACE",
    "MARITAL STATUS",
    "MCH / NOK NAME",
    "MCH / NOK NRIC",
    "MCH / NOK RELATIONSHIP",
    "MCH / NOK CONTACT NUMBER",
    "MCH / NOK ADDRESS (PORTS)",
    "MCH / NOK ADDRESS (From Student)",
]
PROFILE_FIELDS_2021 = [
    "pris_no",
    "category",
    "edr_ros",
    "verification_note",
    "ic_number",
    "name",
    "class_name",
    "status",
    "status_effective",
    "admission_type",
    "exam_level",
    "date_of_birth",
    "age_in_academic_year",
    "gender",
    "language_1",
    "language_2",
    "math_1",
    "math_2",
    "science",
    "humanities",
    "commerce_1",
    "commerce_2",
    "commerce_3",
    "elective",
    "aa",
    "nationality",
    "birthplace",
    "religion",
    "race",
    "marital_status",
    "next_of_kin_name",
    "next_of_kin_nric",
    "next_of_kin_relationship",
    "next_of_kin_contact",
    "next_of_kin_address_ports",
    "next_of_kin_address_from_student",
]


def workbook(
    rows, *, formula_row: int | None = None, error_cell_row: int | None = None, formula_age=False, cached_formula_value="23", headers=None
) -> bytes:
    output = BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = "Student Intake 2023"
    headers = headers or HEADERS
    ws.append(headers)
    fields = PROFILE_FIELDS if headers is HEADERS else None
    for position, payload in enumerate(rows, start=1):
        values = [position]
        for header_index, _header in enumerate(headers[1:], start=1):
            field = fields[header_index - 1] if fields else None
            value = payload.get(field) if field else None
            values.append(value)
        ws.append(values)
        if formula_row == position:
            ws.cell(row=position + 1, column=6, value="=1+1")
        if error_cell_row == position:
            error_cell = ws.cell(row=position + 1, column=6, value="#VALUE!")
            error_cell.data_type = "e"
        if formula_age and position == 1:
            ws.cell(row=position + 1, column=13, value="=20+3")
    wb.save(output)
    data = output.getvalue()
    if not formula_age:
        return data
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ET.register_namespace("", namespace)
    updated = BytesIO()
    with zipfile.ZipFile(BytesIO(data)) as original, zipfile.ZipFile(updated, "w", zipfile.ZIP_DEFLATED) as result:
        for entry in original.infolist():
            content = original.read(entry.filename)
            if entry.filename == "xl/worksheets/sheet1.xml":
                root = ET.fromstring(content)
                age_cell = root.find(f".//{{{namespace}}}c[@r='M2']")
                age_value = age_cell.find(f"{{{namespace}}}v")
                age_value.text = cached_formula_value
                content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            result.writestr(entry, content)
    return updated.getvalue()


def workbook_2021(rows, *, formula_age=False, cached_formula_value="21", hidden=False):
    output = BytesIO()
    wb = Workbook()
    ws = wb.active
    ws.title = "Student Intake 2021"
    if hidden:
        wb.create_sheet("Visible dashboard")
        ws.sheet_state = "hidden"
    ws.append(HEADERS_2021)
    for position, payload in enumerate(rows, start=1):
        ws.append([position, *(payload.get(field) for field in PROFILE_FIELDS_2021)])
        if formula_age:
            ws.cell(row=position + 1, column=14, value="=20+1")
    wb.save(output)
    data = output.getvalue()
    if not formula_age:
        return data
    namespace = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    ET.register_namespace("", namespace)
    updated = BytesIO()
    with zipfile.ZipFile(BytesIO(data)) as original, zipfile.ZipFile(updated, "w", zipfile.ZIP_DEFLATED) as result:
        for entry in original.infolist():
            content = original.read(entry.filename)
            if entry.filename == "xl/worksheets/sheet1.xml":
                root = ET.fromstring(content)
                age_cell = root.find(f".//{{{namespace}}}c[@r='N2']")
                age_value = age_cell.find(f"{{{namespace}}}v")
                age_value.text = cached_formula_value
                content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            result.writestr(entry, content)
    return updated.getvalue()


def intake_row(pris_no=None, **changes):
    return {
        "pris_no": pris_no or "INTAKE-" + uuid4().hex[:10].upper(),
        "category": "OP",
        "edr_ros": "Synthetic EDR",
        "ic_number": "SYNTH-IC-IMPORT-1",
        "name": "Synthetic Import Student",
        "class_name": "A4 A",
        "status": "ACTIVE",
        "status_effective": date(2026, 1, 2),
        "admission_type": "Synthetic admission",
        "exam_level": "Synthetic exam",
        "date_of_birth": date(2000, 1, 2),
        "age_in_academic_year": 23,
        "gender": "Synthetic gender",
        "language_1": "Synthetic language",
        "language_2": "Synthetic language 2",
        "math_1": "Synthetic math",
        "math_2": "Synthetic math 2",
        "cpa": "Synthetic CPA",
        "science": "Synthetic science",
        "humanities": "Synthetic humanities",
        "commerce_1": "Synthetic commerce",
        "commerce_2": "Synthetic commerce 2",
        "commerce_3": "Synthetic commerce 3",
        "aa": "Synthetic AA",
        "nationality": "Synthetic nationality",
        "citizenship": "Synthetic citizenship",
        "birthplace": "Synthetic birthplace",
        "religion": "Synthetic religion",
        "race": "Synthetic race",
        "marital_status": "Synthetic marital status",
        "next_of_kin_name": "Synthetic next of kin",
        "next_of_kin_nric": "SYNTH-NRIC-IMPORT-1",
        "next_of_kin_relationship": "Synthetic relationship",
        "next_of_kin_contact": "0000-1111",
        "next_of_kin_address_ports": "Synthetic port address",
        "next_of_kin_address_from_student": "Synthetic home address",
        "student_contact": "1111-2222",
        "verification_note": "Synthetic verification detail",
        "elective": "Synthetic elective",
        **changes,
    }


def upload(client, headers, content, source_workbook="STUDENT_INTAKE_2023"):
    mappings = client.get("/api/v1/student-reference/class-mappings", headers=headers["admin"])
    assert mappings.status_code == 200, mappings.text
    if not any(row["source_workbook"] == source_workbook and row["source_label"] == "A4 A" for row in mappings.json()):
        class_code = "IM" + uuid4().hex[:8].upper()
        instructional_class = client.post("/api/v1/timetable/classes", json={"code": class_code, "name": "A4 A"}, headers=headers["admin"])
        assert instructional_class.status_code == 201, instructional_class.text
        mapped = client.post(
            "/api/v1/student-reference/class-mappings",
            json={
                "source_workbook": source_workbook,
                "source_label": "A4 A",
                "instructional_class_id": instructional_class.json()["id"],
            },
            headers=headers["admin"],
        )
        assert mapped.status_code == 201, mapped.text
    return client.post(f"{BASE}?source_workbook={source_workbook}", content=content, headers={**headers["operator"], "Content-Type": XLSX})


def test_parser_maps_supported_2023_headers_and_keeps_values_private():
    from app.student_import import parse_student_workbook

    candidate = intake_row("PARSE-0001")
    parsed = parse_student_workbook(workbook([candidate]))
    assert len(parsed) == 1 and parsed[0]["errors"] == []
    fields = parsed[0]["fields"]
    assert fields["pris_no"] == "PARSE-0001"
    assert fields["language_1"] == "Synthetic language"
    assert fields["math_2"] == "Synthetic math 2"
    assert fields["academic_year"] == "2023" and fields["age_in_academic_year"] == 23
    assert fields["next_of_kin_address_from_student"] == "Synthetic home address"
    assert fields["date_of_birth"] == "2000-01-02"


def test_parser_maps_supported_2021_headers_and_year_specific_fields():
    from app.student_import import parse_student_workbook

    candidate = intake_row("PARSE-2021-0001", age_in_academic_year=21)
    parsed = parse_student_workbook(workbook_2021([candidate]), "STUDENT_INTAKE_2021")
    assert len(parsed) == 1 and parsed[0]["errors"] == []
    fields = parsed[0]["fields"]
    assert fields["pris_no"] == "PARSE-2021-0001"
    assert fields["class_name"] == "A4 A"
    assert fields["academic_year"] == "2021" and fields["age_in_academic_year"] == 21
    assert fields["verification_note"] == "Synthetic verification detail"
    assert fields["elective"] == "Synthetic elective"
    assert fields["citizenship"] is None and fields["student_contact"] is None


def test_parser_accepts_the_explicitly_selected_hidden_2021_worksheet():
    from app.student_import import parse_student_workbook

    parsed = parse_student_workbook(
        workbook_2021([intake_row("PARSE-HIDDEN-2021")], hidden=True),
        "STUDENT_INTAKE_2021",
    )
    assert len(parsed) == 1 and parsed[0]["errors"] == []
    assert parsed[0]["fields"]["pris_no"] == "PARSE-HIDDEN-2021"


def test_parser_reads_cached_2021_age_formula_and_rejects_unknown_source():
    from app.student_import import ImportFileError, parse_student_workbook

    parsed = parse_student_workbook(workbook_2021([intake_row("AGE-2021-FORMULA")], formula_age=True), "STUDENT_INTAKE_2021")
    assert parsed[0]["fields"]["age_in_academic_year"] == 21
    assert parsed[0]["fields"]["academic_year"] == "2021"
    with pytest.raises(ImportFileError, match="unsupported_workbook"):
        parse_student_workbook(workbook_2021([intake_row("UNKNOWN-SOURCE")]), "STUDENT_INTAKE_2019")


def test_2021_import_uses_its_own_class_crosswalk_and_preserves_every_supported_field(lesson_context):
    client, headers, _ = lesson_context
    academic_years = client.get("/api/v1/student-reference/catalogs/academic-years", headers=headers["admin"]).json()
    if not any(value["name"] == "2021" for value in academic_years):
        created_year = client.post("/api/v1/student-reference/catalogs/academic-years", json={"name": "2021"}, headers=headers["admin"])
        assert created_year.status_code == 201, created_year.text

    response = upload(
        client,
        headers,
        workbook_2021([intake_row("IMPORT-2021-0001", age_in_academic_year=21)]),
        source_workbook="STUDENT_INTAKE_2021",
    )
    assert response.status_code == 201, response.text
    preview = response.json()
    assert preview["source_workbook"] == "STUDENT_INTAKE_2021"
    assert preview["valid_count"] == 1 and preview["invalid_count"] == 0
    committed = client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"])
    assert committed.status_code == 200, committed.text
    assert committed.json()["source_workbook"] == "STUDENT_INTAKE_2021"
    student = client.get("/api/v1/students?q=IMPORT-2021-0001", headers=headers["operator"]).json()[0]
    assert student["academic_year"] == "2021" and student["age_in_academic_year"] == 21
    assert student["verification_note"] == "Synthetic verification detail"
    assert student["elective"] == "Synthetic elective"
    with SessionLocal() as db:
        saved = db.scalar(select(Student).where(Student.pris_no == "IMPORT-2021-0001"))
        assert saved.verification_note_encrypted != "Synthetic verification detail"
        assert decrypt_sensitive(saved.verification_note_encrypted) == "Synthetic verification detail"


def test_import_retention_is_admin_only_dry_run_and_expires_preview_payloads(lesson_context, monkeypatch):
    from app.config import get_settings
    from app.routes import student_imports

    client, headers, _ = lesson_context
    settings = get_settings().model_copy(update={"student_import_retention_days": 1})
    monkeypatch.setattr(student_imports, "get_settings", lambda: settings)
    preview = upload(client, headers, workbook([intake_row()])).json()
    with SessionLocal() as db:
        batch = db.get(StudentImportBatch, preview["id"])
        batch.created_at = datetime.now(UTC) - timedelta(days=2)
        db.commit()

    retention_path = f"{BASE}/retention"
    purge_path = f"{BASE}/retention/purge"
    assert client.get(retention_path, headers=headers["operator"]).status_code == 403
    assert client.get(retention_path, headers=headers["executive"]).status_code == 403
    assert client.post(purge_path, json={"apply": True}, headers=headers["operator"]).status_code == 403
    status_response = client.get(retention_path, headers=headers["admin"])
    assert status_response.status_code == 200, status_response.text
    assert status_response.json()["eligible_preview_batches"] == 1

    dry_run = client.post(purge_path, json={"apply": False}, headers=headers["admin"])
    assert dry_run.status_code == 200, dry_run.text
    assert dry_run.json()["eligible_batches"] == 1 and not dry_run.json()["applied"]
    purge_token = dry_run.json()["purge_token"]
    assert purge_token
    assert client.post(purge_path, json={"apply": True}, headers=headers["admin"]).status_code == 409
    with SessionLocal() as db:
        batch = db.get(StudentImportBatch, preview["id"])
        assert batch.status == "PREVIEW" and batch.source_ciphertext and batch.rows_ciphertext

    apply = client.post(purge_path, json={"apply": True, "purge_token": purge_token}, headers=headers["admin"])
    assert apply.status_code == 200, apply.text
    assert apply.json()["purged_batches"] == 1 and apply.json()["eligible_batches"] == 0
    expired = client.get(f"{BASE}/{preview['id']}", headers=headers["operator"])
    assert expired.status_code == 200 and expired.json()["status"] == "EXPIRED"
    assert expired.json()["expired"] and not expired.json()["payload_available"]
    assert expired.json()["row_errors"] == [] and expired.json()["row_warnings"] == []
    assert client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"]).status_code == 410
    repeated = client.post(purge_path, json={"apply": True, "purge_token": purge_token}, headers=headers["admin"])
    assert repeated.status_code == 200 and repeated.json()["purged_batches"] == 0
    with SessionLocal() as db:
        batch = db.get(StudentImportBatch, preview["id"])
        assert batch.source_ciphertext is None and batch.rows_ciphertext is None and batch.payload_purged_at
        assert (
            db.scalar(
                select(func.count(AuditEvent.id)).where(
                    AuditEvent.action == "student.import_payload.purged", AuditEvent.entity_id == str(batch.id)
                )
            )
            == 1
        )


def test_import_retention_preserves_committed_student_and_idempotent_result(lesson_context, monkeypatch):
    from app.config import get_settings
    from app.routes import student_imports

    client, headers, _ = lesson_context
    settings = get_settings().model_copy(update={"student_import_retention_days": 1})
    monkeypatch.setattr(student_imports, "get_settings", lambda: settings)
    student_identifier = "RETENTION-" + uuid4().hex[:10].upper()
    preview = upload(client, headers, workbook([intake_row(student_identifier)])).json()
    committed = client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"])
    assert committed.status_code == 200, committed.text
    expected_result = committed.json()["result"]
    with SessionLocal() as db:
        batch = db.get(StudentImportBatch, preview["id"])
        batch.created_at = datetime.now(UTC) - timedelta(days=2)
        db.commit()

    dry_run = client.post(f"{BASE}/retention/purge", json={"apply": False}, headers=headers["admin"])
    assert dry_run.status_code == 200 and dry_run.json()["purge_token"]
    purged = client.post(
        f"{BASE}/retention/purge",
        json={"apply": True, "purge_token": dry_run.json()["purge_token"]},
        headers=headers["admin"],
    )
    assert purged.status_code == 200 and purged.json()["purged_batches"] == 1
    after_purge = client.get(f"{BASE}/{preview['id']}", headers=headers["operator"])
    assert after_purge.status_code == 200
    assert after_purge.json()["status"] == "COMMITTED" and not after_purge.json()["payload_available"]
    assert after_purge.json()["result"] == expected_result
    idempotent_commit = client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"])
    assert idempotent_commit.status_code == 200 and idempotent_commit.json()["result"] == expected_result
    with SessionLocal() as db:
        assert db.scalar(select(func.count(Student.id)).where(Student.pris_no == student_identifier)) == 1
        batch = db.get(StudentImportBatch, preview["id"])
        assert batch.status == "COMMITTED" and batch.result_json
        assert batch.source_ciphertext is None and batch.rows_ciphertext is None


def test_import_retention_purge_token_is_actor_bound_and_rejects_stale_preview(lesson_context, monkeypatch):
    from app.config import get_settings
    from app.routes import student_imports

    client, headers, _ = lesson_context
    settings = get_settings().model_copy(update={"student_import_retention_days": 1})
    monkeypatch.setattr(student_imports, "get_settings", lambda: settings)
    first = upload(client, headers, workbook([intake_row()])).json()
    second = upload(client, headers, workbook([intake_row()])).json()
    with SessionLocal() as db:
        db.get(StudentImportBatch, first["id"]).created_at = datetime.now(UTC) - timedelta(days=2)
        db.commit()

    dry_run = client.post(f"{BASE}/retention/purge", json={"apply": False}, headers=headers["admin"])
    assert dry_run.status_code == 200 and dry_run.json()["eligible_batches"] == 1
    token = dry_run.json()["purge_token"]
    denied = client.post(f"{BASE}/retention/purge", json={"apply": True, "purge_token": token}, headers=headers["superuser"])
    assert denied.status_code == 409

    with SessionLocal() as db:
        db.get(StudentImportBatch, second["id"]).created_at = datetime.now(UTC) - timedelta(days=2)
        db.commit()
    stale = client.post(f"{BASE}/retention/purge", json={"apply": True, "purge_token": token}, headers=headers["admin"])
    assert stale.status_code == 409
    with SessionLocal() as db:
        assert all(db.get(StudentImportBatch, batch_id).source_ciphertext is not None for batch_id in (first["id"], second["id"]))
        for batch_id in (first["id"], second["id"]):
            db.get(StudentImportBatch, batch_id).created_at = datetime.now(UTC)
        db.commit()


def test_student_import_retention_disabled_rejects_apply_and_roles_stay_scoped(lesson_context, monkeypatch):
    from app.config import get_settings
    from app.routes import student_imports

    client, headers, _ = lesson_context
    settings = get_settings().model_copy(update={"student_import_retention_days": 0})
    monkeypatch.setattr(student_imports, "get_settings", lambda: settings)
    assert client.get(f"{BASE}/retention", headers=headers["admin"]).json()["enabled"] is False
    disabled = client.post(f"{BASE}/retention/purge", json={"apply": True}, headers=headers["admin"])
    assert disabled.status_code == 409
    upload_denied = client.post(BASE, content=b"not an upload", headers=headers["admin"])
    assert upload_denied.status_code == 403


def test_parser_rejects_formulas_unknown_headers_numeric_identifiers_and_bad_archives():
    from app.student_import import ImportFileError, parse_student_workbook

    parsed = parse_student_workbook(workbook([intake_row("FORMULA-1")], formula_row=1))
    assert parsed[0]["errors"] == [{"field": "name", "code": "formula_not_allowed"}]
    parsed = parse_student_workbook(workbook([intake_row("EXCEL-ERROR-1")], error_cell_row=1))
    assert parsed[0]["errors"] == [{"field": "name", "code": "excel_error_value"}]
    numeric_id = intake_row("NUMERIC-1")
    numeric_id["ic_number"] = 123456
    parsed = parse_student_workbook(workbook([numeric_id]))
    assert parsed[0]["errors"] == []
    assert parsed[0]["warnings"] == [{"field": "ic_number", "code": "numeric_cell_may_lose_leading_zeros"}]
    numeric_pris_no = intake_row(123456)
    parsed = parse_student_workbook(workbook([numeric_pris_no]))
    assert {error["code"] for error in parsed[0]["errors"]} == {"identifier_must_be_text", "required"}
    with pytest.raises(ImportFileError, match="unsupported_header"):
        parse_student_workbook(workbook([intake_row()], headers=[*HEADERS, "Unmapped PII column"]))
    with pytest.raises(ImportFileError, match="invalid_xlsx"):
        parse_student_workbook(b"not an Excel file")


def test_parser_uses_cached_age_formula_value_from_supported_workbook():
    from app.student_import import parse_student_workbook

    parsed = parse_student_workbook(workbook([intake_row("AGE-FORMULA-1")], formula_age=True))
    assert parsed[0]["errors"] == []
    assert parsed[0]["fields"]["age_in_academic_year"] == 23
    assert parsed[0]["fields"]["academic_year"] == "2023"
    missing_cache = parse_student_workbook(workbook([intake_row("AGE-FORMULA-NOCACHE")], formula_age=True, cached_formula_value=""))
    assert "formula_value_missing" in {error["code"] for error in missing_cache[0]["errors"]}


def test_parser_rejects_oversized_and_high_compression_archives():
    from app.student_import import MAX_UPLOAD_BYTES, ImportFileError, parse_student_workbook

    with pytest.raises(ImportFileError, match="file_too_large"):
        parse_student_workbook(b"0" * (MAX_UPLOAD_BYTES + 1))
    compressed = BytesIO()
    with zipfile.ZipFile(compressed, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("padding.xml", "0" * 300_000)
    with pytest.raises(ImportFileError, match="invalid_xlsx"):
        parse_student_workbook(compressed.getvalue())


def test_preview_is_operator_only_sanitized_encrypted_and_detects_duplicates(lesson_context):
    client, headers, _ = lesson_context
    duplicate = intake_row("DUPLICATE-IMPORT")
    bad = intake_row("BAD-IMPORT", name=None)
    raw = workbook([duplicate, duplicate.copy(), bad])
    response = upload(client, headers, raw)
    assert response.status_code == 201, response.text
    preview = response.json()
    assert (preview["row_count"], preview["valid_count"], preview["invalid_count"]) == (3, 0, 3)
    assert all("DUPLICATE-IMPORT" not in json.dumps(error) for error in preview["row_errors"])
    assert all(error["code"] in {"duplicate_in_workbook", "required_for_new_profile"} for error in preview["row_errors"])
    superuser_preview = client.post(BASE, content=raw, headers={**headers["superuser"], "Content-Type": XLSX})
    assert superuser_preview.status_code == 201, superuser_preview.text
    assert client.get(f"{BASE}/{superuser_preview.json()['id']}", headers=headers["superuser"]).status_code == 200
    assert client.post(BASE, content=raw, headers={**headers["executive"], "Content-Type": XLSX}).status_code == 403
    with SessionLocal() as db:
        batch = db.get(StudentImportBatch, preview["id"])
        assert b"Synthetic Import Student" not in batch.source_ciphertext
        assert b"SYNTH-NRIC-IMPORT-1" not in batch.source_ciphertext
        assert b"Synthetic Import Student" not in batch.rows_ciphertext
        assert decrypt_sensitive_bytes(batch.source_ciphertext) == raw
        staged = json.loads(decrypt_sensitive_bytes(batch.rows_ciphertext))
        assert staged[0]["fields"]["next_of_kin_nric"] == "SYNTH-NRIC-IMPORT-1"
        assert batch.status == "PREVIEW"
    assert client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"]).status_code == 409
    assert client.get(f"{BASE}/{preview['id']}", headers=headers["executive"]).status_code == 403


def test_unmapped_intake_class_blocks_import_without_echoing_student_data(lesson_context):
    client, headers, _ = lesson_context
    row = intake_row("PRIVATE-UNMAPPED-CLASS")
    row["class_name"] = "Unmapped Source Class " + uuid4().hex[:8]
    response = client.post(BASE, content=workbook([row]), headers={**headers["operator"], "Content-Type": XLSX})
    assert response.status_code == 201, response.text
    preview = response.json()
    assert preview["invalid_count"] == 1
    assert preview["row_errors"] == [{"row_number": 2, "field": "class_name", "code": "unmapped_class"}]
    assert "PRIVATE-UNMAPPED-CLASS" not in response.text and row["class_name"] not in response.text
    denied = client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"])
    assert denied.status_code == 409


def test_class_mappings_are_it_managed_normalized_and_versioned(lesson_context):
    client, headers, references = lesson_context
    mapping_path = "/api/v1/student-reference/class-mappings"
    source_label = "Legacy Intake Class " + uuid4().hex[:8]
    created = client.post(
        mapping_path,
        json={
            "source_workbook": "STUDENT_INTAKE_2023",
            "source_label": f"  {source_label}  ",
            "instructional_class_id": references["instructional_class_id"],
        },
        headers=headers["admin"],
    )
    assert created.status_code == 201, created.text
    mapping = created.json()
    assert mapping["source_label"] == source_label and mapping["version"] == 1
    listed = client.get(mapping_path, headers=headers["operator"])
    assert any(row["id"] == mapping["id"] for row in listed.json())
    duplicate = client.post(
        mapping_path,
        json={"source_label": source_label.upper(), "instructional_class_id": references["instructional_class_id"]},
        headers=headers["admin"],
    )
    assert duplicate.status_code == 409
    denied = client.post(
        mapping_path,
        json={"source_label": "Operator Cannot Map", "instructional_class_id": references["instructional_class_id"]},
        headers=headers["operator"],
    )
    assert denied.status_code == 403
    superuser_mapping = client.post(
        mapping_path,
        json={"source_label": "Superuser Can Map", "instructional_class_id": references["instructional_class_id"]},
        headers=headers["superuser"],
    )
    assert superuser_mapping.status_code == 201
    stale = client.patch(f"{mapping_path}/{mapping['id']}", json={"expected_version": 2, "is_active": False}, headers=headers["admin"])
    assert stale.status_code == 409
    updated = client.patch(f"{mapping_path}/{mapping['id']}", json={"expected_version": 1, "is_active": False}, headers=headers["admin"])
    assert updated.status_code == 200 and updated.json()["version"] == 2 and not updated.json()["is_active"]


def test_import_uses_canonical_class_and_rejects_mapping_changes_after_preview(lesson_context):
    client, headers, references = lesson_context
    class_path = "/api/v1/timetable/classes"
    source_class = client.post(
        class_path,
        json={"code": "SRC" + uuid4().hex[:8].upper(), "name": "Canonical Intake Class"},
        headers=headers["admin"],
    )
    target_class = client.post(
        class_path,
        json={"code": "DST" + uuid4().hex[:8].upper(), "name": "Replacement Intake Class"},
        headers=headers["admin"],
    )
    assert source_class.status_code == 201 and target_class.status_code == 201
    mappings_path = "/api/v1/student-reference/class-mappings"
    mapping = client.post(
        mappings_path,
        json={"source_label": "Legacy Class Alias " + uuid4().hex[:8], "instructional_class_id": source_class.json()["id"]},
        headers=headers["admin"],
    ).json()
    row = intake_row("CLASS-MAPPING-STALE")
    row["class_name"] = " " + mapping["source_label"].upper().replace(" ", "   ") + " "
    content = workbook([row])
    preview = upload(client, headers, content).json()
    assert preview["valid_count"] == 1
    changed_mapping = client.patch(
        f"{mappings_path}/{mapping['id']}",
        json={"expected_version": mapping["version"], "instructional_class_id": target_class.json()["id"]},
        headers=headers["admin"],
    )
    assert changed_mapping.status_code == 200 and changed_mapping.json()["version"] == 2
    stale_commit = client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"])
    assert stale_commit.status_code == 409 and "class mapping changed" in stale_commit.json()["detail"].lower()
    fresh_preview = upload(client, headers, content).json()
    committed = client.post(f"{BASE}/{fresh_preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"])
    assert committed.status_code == 200, committed.text
    saved = client.get("/api/v1/students?q=CLASS-MAPPING-STALE", headers=headers["operator"]).json()[0]
    assert saved["class_name"] == "Replacement Intake Class"
    assert references["instructional_class_id"] != source_class.json()["id"]


def test_create_only_import_is_encrypted_atomic_idempotent_and_audited(lesson_context):
    client, headers, _ = lesson_context
    first = intake_row("IMPORT-CREATE-1")
    second = intake_row("IMPORT-CREATE-2", name="Second Synthetic Import Student")
    raw = workbook([first, second])
    preview = upload(client, headers, raw).json()
    assert preview["valid_count"] == 2 and preview["new_count"] == 2
    committed = client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"])
    assert committed.status_code == 200, committed.text
    result = committed.json()
    assert result["status"] == "COMMITTED" and result["result"] == {
        "created": 2,
        "mode": "CREATE_ONLY",
        "unchanged": 0,
        "updated": 0,
        "data_warnings_acknowledged": False,
    }
    assert (
        client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"]).json()["result"]
        == result["result"]
    )
    with SessionLocal() as db:
        saved = db.scalar(select(Student).where(Student.pris_no == first["pris_no"]))
        imported_ids = db.scalars(select(Student.id).where(Student.pris_no.in_([first["pris_no"], second["pris_no"]]))).all()
        assert saved.version == 1
        assert saved.ic_number_encrypted != first["ic_number"]
        assert saved.next_of_kin_nric_encrypted != first["next_of_kin_nric"]
        assert decrypt_sensitive(saved.ic_number_encrypted) == first["ic_number"]
        history = db.scalars(select(StudentStatusHistory).where(StudentStatusHistory.student_id == saved.id)).all()
        assert len(history) == 1 and history[0].new_status == "ACTIVE"
        events = db.scalars(
            select(AuditEvent).where(AuditEvent.entity_type == "student_import_batch", AuditEvent.entity_id == str(preview["id"]))
        ).all()
        assert len(events) == 2
        student_events = db.scalars(
            select(AuditEvent).where(
                AuditEvent.action == "student.imported",
                AuditEvent.entity_id.in_([str(student_id) for student_id in imported_ids]),
            )
        ).all()
        assert len(student_events) == 2
        assert all(first["ic_number"] not in event.details_json for event in [*events, *student_events])
        assert db.get(StudentImportBatch, preview["id"]).status == "COMMITTED"


def test_numeric_identity_and_contact_cells_require_explicit_data_warning_acknowledgement(lesson_context):
    client, headers, _ = lesson_context
    candidate = intake_row(
        "NUMERIC-CELL-IMPORT",
        ic_number=1234567890123,
        next_of_kin_nric=1234567890123,
        next_of_kin_contact=12345678,
        student_contact=1234567890,
    )
    preview = upload(client, headers, workbook([candidate])).json()
    assert preview["valid_count"] == 1 and preview["warning_count"] == 4
    assert {warning["field"] for warning in preview["row_warnings"]} == {
        "ic_number",
        "next_of_kin_nric",
        "next_of_kin_contact",
        "student_contact",
    }
    blocked = client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"])
    assert blocked.status_code == 409 and "Confirm the workbook data warnings" in blocked.json()["detail"]
    committed = client.post(
        f"{BASE}/{preview['id']}/commit",
        json={"mode": "CREATE_ONLY", "confirm_data_warnings": True},
        headers=headers["operator"],
    )
    assert committed.status_code == 200, committed.text
    assert committed.json()["result"]["data_warnings_acknowledged"] is True
    student = client.get("/api/v1/students?q=NUMERIC-CELL-IMPORT", headers=headers["operator"]).json()[0]
    assert student["ic_number"] == "1234567890123"
    assert student["next_of_kin_contact"] == "12345678"
    assert student["student_contact"] == "1234567890"


def test_update_existing_is_explicit_blank_preserving_and_status_historical(lesson_context):
    client, headers, _ = lesson_context
    existing = client.post(
        "/api/v1/students",
        json={
            "pris_no": "IMPORT-UPDATE-1",
            "name": "Original import student",
            "class_name": "A4 A",
            "category": "OP",
            "status_effective": "2026-01-02",
            "ic_number": "KEEP-IC",
            "next_of_kin_name": "Keep next of kin",
        },
        headers=headers["operator"],
    ).json()
    incoming = intake_row(
        "IMPORT-UPDATE-1",
        name=None,
        class_name=None,
        category=None,
        status="INACTIVE",
        status_effective=date(2026, 3, 4),
        ic_number=None,
        next_of_kin_name=None,
    )
    new = intake_row("IMPORT-UPDATE-NEW", name="New import row")
    preview = upload(client, headers, workbook([incoming, new])).json()
    assert (preview["existing_count"], preview["new_count"]) == (1, 1)
    denied = client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"])
    assert denied.status_code == 409
    assert client.get(f"/api/v1/students/{existing['id']}", headers=headers["operator"]).json()["name"] == "Original import student"
    assert client.get("/api/v1/students?q=IMPORT-UPDATE-NEW", headers=headers["operator"]).json() == []
    committed = client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "UPDATE_EXISTING"}, headers=headers["operator"])
    assert committed.status_code == 200, committed.text
    assert committed.json()["result"] == {
        "created": 1,
        "mode": "UPDATE_EXISTING",
        "unchanged": 0,
        "updated": 1,
        "data_warnings_acknowledged": False,
    }
    saved = client.get(f"/api/v1/students/{existing['id']}", headers=headers["operator"]).json()
    assert saved["version"] == 2 and saved["name"] == "Original import student"
    assert saved["class_name"] == "A4 A" and saved["category"] == "OP"
    assert saved["edr_ros"] == "Synthetic EDR"
    assert saved["ic_number"] == "KEEP-IC" and saved["next_of_kin_name"] == "Keep next of kin"
    assert saved["status"] == "INACTIVE" and saved["status_effective"] == "2026-03-04"
    history = client.get(f"/api/v1/students/{existing['id']}/status-history", headers=headers["operator"]).json()
    assert [item["new_status"] for item in history] == ["ACTIVE", "INACTIVE"]
    assert history[-1]["effective_date"] == "2026-03-04"


def test_import_validates_reference_catalog_values_and_rejects_stale_preview(lesson_context):
    client, headers, _ = lesson_context
    unknown = upload(client, headers, workbook([intake_row("IMPORT-UNKNOWN-CATEGORY", category="Unconfigured category")])).json()
    assert unknown["invalid_count"] == 1
    assert any(error["field"] == "category" and error["code"] == "unknown_reference_value" for error in unknown["row_errors"])
    denied = client.post(f"{BASE}/{unknown['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"])
    assert denied.status_code == 409

    category = f"IMP-{uuid4().hex[:8]}"
    catalog_path = "/api/v1/student-reference/catalogs/categories"
    created = client.post(catalog_path, json={"name": category}, headers=headers["admin"])
    assert created.status_code == 201
    preview = upload(client, headers, workbook([intake_row("IMPORT-STALE-CATEGORY", category=category)])).json()
    assert preview["valid_count"] == 1 and preview["invalid_count"] == 0
    archived = client.patch(
        f"{catalog_path}/{created.json()['id']}",
        json={"expected_version": 1, "is_active": False},
        headers=headers["admin"],
    )
    assert archived.status_code == 200
    result = client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"])
    assert result.status_code == 409
    assert client.get("/api/v1/students?q=IMPORT-STALE-CATEGORY", headers=headers["operator"]).json() == []
    restored = client.patch(
        f"{catalog_path}/{created.json()['id']}",
        json={"expected_version": 2, "is_active": True},
        headers=headers["admin"],
    )
    assert restored.status_code == 200


def test_import_matches_legacy_identifier_case_and_whitespace_without_creating_duplicate(lesson_context):
    client, headers, _ = lesson_context
    with SessionLocal() as db:
        saved = Student(
            pris_no=" legacy-import-1 ",
            name_encrypted=encrypt_sensitive("Legacy profile"),
            class_name="A4 A",
            category="OP",
            status="ACTIVE",
            created_by=1,
        )
        db.add(saved)
        db.commit()
        student_id = saved.id
    preview = upload(client, headers, workbook([intake_row("LEGACY-IMPORT-1", name="Reconciled profile")])).json()
    assert preview["existing_count"] == 1 and preview["new_count"] == 0
    committed = client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "UPDATE_EXISTING"}, headers=headers["operator"])
    assert committed.status_code == 200, committed.text
    assert committed.json()["result"]["created"] == 0 and committed.json()["result"]["updated"] == 1
    assert client.get("/api/v1/students?q=LEGACY-IMPORT-1", headers=headers["operator"]).json()[0]["id"] == student_id


def test_import_preview_stale_profile_rejects_whole_batch_and_preserves_other_rows(lesson_context):
    client, headers, _ = lesson_context
    existing = client.post(
        "/api/v1/students",
        json={"pris_no": "IMPORT-STALE-1", "name": "Before import", "class_name": "A4 A", "category": "OP"},
        headers=headers["operator"],
    ).json()
    new = intake_row("IMPORT-STALE-NEW")
    preview = upload(client, headers, workbook([intake_row("IMPORT-STALE-1", name="Staged name"), new])).json()
    changed = client.patch(
        f"/api/v1/students/{existing['id']}", json={"expected_version": 1, "name": "Manual winner"}, headers=headers["operator"]
    )
    assert changed.status_code == 200
    result = client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "UPDATE_EXISTING"}, headers=headers["operator"])
    assert result.status_code == 409
    assert client.get("/api/v1/students?q=IMPORT-STALE-NEW", headers=headers["operator"]).json() == []
    assert client.get(f"/api/v1/students/{existing['id']}", headers=headers["operator"]).json()["name"] == "Manual winner"
    assert client.get(f"{BASE}/{preview['id']}", headers=headers["operator"]).json()["status"] == "PREVIEW"


def test_import_transaction_failure_rolls_back_profiles_history_and_batch_status(lesson_context, monkeypatch):
    from app.routes import student_imports

    client, headers, _ = lesson_context
    preview = upload(client, headers, workbook([intake_row("IMPORT-ROLLBACK-1")])).json()
    with SessionLocal() as db:
        history_count = db.scalar(select(func.count()).select_from(StudentStatusHistory))

    def fail(*_args, **_kwargs):
        raise RuntimeError("Injected audit failure")

    monkeypatch.setattr(student_imports, "record_event", fail)
    with pytest.raises(RuntimeError, match="Injected audit failure"):
        client.post(f"{BASE}/{preview['id']}/commit", json={"mode": "CREATE_ONLY"}, headers=headers["operator"])
    assert client.get("/api/v1/students?q=IMPORT-ROLLBACK-1", headers=headers["operator"]).json() == []
    with SessionLocal() as db:
        batch = db.get(StudentImportBatch, preview["id"])
        assert batch.status == "PREVIEW" and batch.committed_at is None
        assert db.scalar(select(Student).where(Student.pris_no == "IMPORT-ROLLBACK-1")) is None
        assert db.scalar(select(func.count()).select_from(StudentStatusHistory)) == history_count


def test_upload_type_limit_and_batch_owner_access(lesson_context):
    client, headers, _ = lesson_context
    assert client.post(BASE, content=b"", headers={**headers["operator"], "Content-Type": "application/json"}).status_code == 415
    assert client.post(BASE, content=b"not xlsx", headers={**headers["operator"], "Content-Type": XLSX}).status_code == 422
    from app.models import User
    from app.security import hash_password

    username = "other-import-operator-" + uuid4().hex[:8]
    password = "other-import-operator-password"
    with SessionLocal() as db:
        db.add(User(username=username, password_hash=hash_password(password), role="Operator", must_change_password=False, is_active=True))
        db.commit()
    login = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    preview = upload(client, headers, workbook([intake_row("IMPORT-OWNER")])).json()
    assert client.get(f"{BASE}/{preview['id']}", headers=other_headers).status_code == 404
