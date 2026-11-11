from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

from openpyxl import Workbook
from playwright.sync_api import expect
from sqlalchemy import select

from app.config import get_settings
from app.crypto import decrypt_sensitive, encrypt_sensitive_bytes
from app.db import SessionLocal
from app.models import InstructionalClass, Student, StudentClassMapping, StudentImportBatch, StudentReferenceValue
from app.student_class_mapping import STUDENT_INTAKE_2021, STUDENT_INTAKE_2023, normalize_source_class_label

from .test_browser import login

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _workbook(pris_no, *, name, ic_number, class_label="Browser Intake Class"):
    output = BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Student Intake 2023"
    sheet.append(["S/N", "Pris No.", "CAT", "IC", "NAME", "INSTN CLASS", "STATUS", "STATUS EFFECTIVE"])
    sheet.append([1, pris_no, "OP", ic_number, name, class_label, "ACTIVE", "2026-01-02"])
    workbook.save(output)
    return output.getvalue()


def _workbook_2021(pris_no, *, name, class_label, verification_note, elective):
    output = BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Student Intake 2021"
    sheet.append(["S/N", "PRIS NO", "CAT", "VERIFY", "NAME", "CLASS", "AGE IN AY'21", "ELECTIVE", "STATUS"])
    sheet.append([1, pris_no, "OP", verification_note, name, class_label, 21, elective, "ACTIVE"])
    workbook.save(output)
    return output.getvalue()


def _upload(page, *, name, data, source_workbook=STUDENT_INTAKE_2023):
    page.locator("#student-import-form select[name=source_workbook]").select_option(source_workbook)
    page.locator("#student-import-form input[name=workbook]").set_input_files({"name": name, "mimeType": XLSX, "buffer": data})
    page.get_by_role("button", name="Upload and preview", exact=True).click()


def _create_class_mapping(account, source_label, source_workbook=STUDENT_INTAKE_2023):
    label, source_key = normalize_source_class_label(source_label)
    with SessionLocal() as db:
        instructional_class = InstructionalClass(
            code="B" + uuid4().hex[:10].upper(),
            name=f"Canonical {label}",
            created_by=account["id"],
        )
        db.add(instructional_class)
        db.flush()
        db.add(
            StudentClassMapping(
                source_workbook=source_workbook,
                source_label=label,
                source_key=source_key,
                instructional_class_id=instructional_class.id,
                created_by=account["id"],
            )
        )
        db.commit()


def test_operator_import_preview_create_and_explicit_update_preserves_blank_cells(page, make_account):
    account = make_account()
    pris_no = "BROWSER-IMPORT-" + uuid4().hex[:8].upper()
    source_class = "Browser Intake " + uuid4().hex[:8]
    _create_class_mapping(account, source_class)
    login(page, account)
    page.get_by_role("button", name="Student profiles", exact=True).click()
    _upload(
        page,
        name="synthetic-intake.xlsx",
        data=_workbook(pris_no, name="Original import name", ic_number="SYNTH-BROWSER-IC", class_label=source_class),
    )
    expect(page.locator("#student-import-summary")).to_contain_text("1 rows; 1 valid; 0 invalid")
    page.get_by_role("button", name="Create new profiles only", exact=True).click()
    expect(page.locator("#student-import-summary")).to_contain_text("Status: COMMITTED")
    expect(page.get_by_role("status")).to_contain_text("1 created")

    _upload(
        page,
        name="updated-intake.xlsx",
        data=_workbook(pris_no, name="Updated import name", ic_number=None, class_label=source_class),
    )
    expect(page.locator("#student-import-summary")).to_contain_text("1 match existing profiles; 0 new identifiers")
    expect(page.get_by_role("button", name="Create new profiles only", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Update existing profiles", exact=True)).to_be_enabled()
    page.get_by_role("button", name="Update existing profiles", exact=True).click()
    expect(page.locator("#student-import-summary")).to_contain_text("Status: COMMITTED")
    expect(page.get_by_role("status")).to_contain_text("1 updated")
    with SessionLocal() as db:
        saved = db.scalar(select(Student).where(Student.pris_no == pris_no))
        assert decrypt_sensitive(saved.name_encrypted) == "Updated import name"
        assert decrypt_sensitive(saved.ic_number_encrypted) == "SYNTH-BROWSER-IC"


def test_operator_can_preview_and_commit_2021_intake_without_losing_legacy_fields(page, make_account):
    account = make_account()
    pris_no = "BROWSER-2021-" + uuid4().hex[:8].upper()
    source_class = "Browser 2021 Class " + uuid4().hex[:8]
    _create_class_mapping(account, source_class, STUDENT_INTAKE_2021)
    with SessionLocal() as db:
        if (
            db.scalar(
                select(StudentReferenceValue.id).where(
                    StudentReferenceValue.catalog_type == "ACADEMIC_YEAR", StudentReferenceValue.name == "2021"
                )
            )
            is None
        ):
            db.add(StudentReferenceValue(catalog_type="ACADEMIC_YEAR", name="2021", normalized_key="2021"))
            db.commit()
    login(page, account)
    page.get_by_role("button", name="Student profiles", exact=True).click()
    _upload(
        page,
        name="synthetic-intake-2021.xlsx",
        data=_workbook_2021(
            pris_no,
            name="Synthetic 2021 student",
            class_label=source_class,
            verification_note="Synthetic legacy verification note",
            elective="Synthetic elective",
        ),
        source_workbook=STUDENT_INTAKE_2021,
    )
    expect(page.locator("#student-import-summary")).to_contain_text("2021 intake batch")
    expect(page.locator("#student-import-summary")).to_contain_text("1 rows; 1 valid; 0 invalid")
    page.get_by_role("button", name="Create new profiles only", exact=True).click()
    expect(page.locator("#student-import-summary")).to_contain_text("Status: COMMITTED")
    with SessionLocal() as db:
        saved = db.scalar(select(Student).where(Student.pris_no == pris_no))
        batch = db.scalar(
            select(StudentImportBatch).where(StudentImportBatch.created_by == account["id"]).order_by(StudentImportBatch.id.desc())
        )
        assert saved is not None and batch is not None
        assert decrypt_sensitive(saved.verification_note_encrypted) == "Synthetic legacy verification note"
        assert saved.elective == "Synthetic elective"
        assert batch.source_workbook == STUDENT_INTAKE_2021


def test_invalid_workbook_preview_shows_field_and_row_without_values(page, make_account):
    account = make_account()
    login(page, account)
    page.get_by_role("button", name="Student profiles", exact=True).click()
    output = BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Student Intake 2023"
    sheet.append(["S/N", "Pris No.", "CAT", "NAME", "INSTN CLASS", "STATUS"])
    sheet.append([1, "PRIVATE-ERROR-ID", "OP", None, "Browser Intake Class", "ACTIVE"])
    workbook.save(output)
    _upload(page, name="invalid-intake.xlsx", data=output.getvalue())
    expect(page.locator("#student-import-summary")).to_contain_text("0 valid; 1 invalid")
    expect(page.locator("#student-import-errors")).to_contain_text("Workbook row 2, name: required for a new profile")
    expect(page.locator("#student-import-errors")).not_to_contain_text("PRIVATE-ERROR-ID")
    expect(page.get_by_role("button", name="Create new profiles only", exact=True)).to_be_disabled()
    expect(page.get_by_role("button", name="Update existing profiles", exact=True)).to_be_disabled()


def test_numeric_identity_warning_requires_operator_acknowledgement(page, make_account):
    account = make_account()
    pris_no = "NUMERIC-WARNING-" + uuid4().hex[:8].upper()
    source_class = "Browser Numeric " + uuid4().hex[:8]
    _create_class_mapping(account, source_class)
    login(page, account)
    page.get_by_role("button", name="Student profiles", exact=True).click()
    _upload(
        page,
        name="numeric-intake.xlsx",
        data=_workbook(pris_no, name="Numeric warning student", ic_number=12345678, class_label=source_class),
    )
    expect(page.locator("#student-import-summary")).to_contain_text("1 data warnings")
    expect(page.locator("#student-import-warning-panel")).to_contain_text("may already have removed leading zeroes")
    expect(page.locator("#student-import-warnings")).to_contain_text(
        "Workbook row 2, ic_number: numeric Excel cell; leading zeroes or long digits may be lost"
    )
    expect(page.get_by_role("button", name="Create new profiles only", exact=True)).to_be_disabled()
    page.get_by_label("I reviewed and accept these numeric-cell values.", exact=True).check()
    expect(page.get_by_role("button", name="Create new profiles only", exact=True)).to_be_enabled()
    page.get_by_role("button", name="Create new profiles only", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("1 created")
    with SessionLocal() as db:
        saved = db.scalar(select(Student).where(Student.pris_no == pris_no))
        assert decrypt_sensitive(saved.ic_number_encrypted) == "12345678"


def test_it_admin_can_create_and_revise_intake_class_mappings(page, make_account):
    account = make_account("IT Administrator")
    source_label = "Legacy Intake " + uuid4().hex[:8]
    class_code = "IT" + uuid4().hex[:8].upper()
    login(page, account)
    page.get_by_role("button", name="Timetable / Schedule", exact=True).click()
    page.get_by_role("button", name="Classes & teachers", exact=True).click()
    page.get_by_role("button", name="Classes & clusters", exact=True).click()
    class_form = page.locator("#timetable-class-form")
    class_form.locator('[name="code"]').fill(class_code)
    class_form.locator('[name="name"]').fill("Canonical Intake Class")
    class_form.get_by_role("button", name="Create class").click()
    expect(page.get_by_role("status")).to_contain_text("Instructional class created")

    mapping_form = page.locator("#student-class-mapping-form")
    expect(mapping_form).to_be_visible()
    mapping_form.locator('[name="source_workbook"]').select_option(STUDENT_INTAKE_2021)
    mapping_form.locator('[name="source_label"]').fill(source_label)
    mapping_form.locator('[name="instructional_class_id"]').select_option(label=f"{class_code} · Canonical Intake Class")
    mapping_form.get_by_role("button", name="Save class mapping").click()
    mapping_row = page.locator("#student-class-mapping-rows tr").filter(has=page.get_by_text(source_label, exact=True))
    expect(mapping_row).to_contain_text("Canonical Intake Class")
    expect(mapping_row).to_contain_text("1")
    expect(mapping_row).to_contain_text(STUDENT_INTAKE_2021)

    second_code = "IT" + uuid4().hex[:8].upper()
    class_form.locator('[name="code"]').fill(second_code)
    class_form.locator('[name="name"]').fill("Replacement Intake Class")
    class_form.get_by_role("button", name="Create class").click()
    mapping_row.get_by_role("combobox", name=f"Target class for {source_label}").select_option(
        label=f"{second_code} · Replacement Intake Class"
    )
    mapping_row.get_by_role("button", name=f"Save mapping for {source_label}").click()
    expect(mapping_row).to_contain_text("Replacement Intake Class")
    expect(mapping_row).to_contain_text("2")


def test_operator_can_review_but_not_edit_intake_class_mappings(page, make_account):
    account = make_account()
    source_label = "Operator Read Only " + uuid4().hex[:8]
    _create_class_mapping(account, source_label)
    login(page, account)
    page.get_by_role("button", name="Timetable / Schedule", exact=True).click()
    page.get_by_role("button", name="Classes & teachers", exact=True).click()
    page.get_by_role("button", name="Classes & clusters", exact=True).click()
    mapping_section = page.locator("#student-class-mapping-section")
    expect(mapping_section).to_be_visible()
    mapping_row = page.locator("#student-class-mapping-rows tr").filter(has=page.get_by_text(source_label, exact=True))
    expect(mapping_row).to_contain_text(f"Canonical {source_label}")
    expect(mapping_row.get_by_role("combobox")).to_be_disabled()
    expect(mapping_row.get_by_role("checkbox")).to_be_disabled()
    expect(mapping_row.get_by_role("button", name=f"Save mapping for {source_label}")).to_be_disabled()
    expect(page.locator("#student-class-mapping-form")).to_be_hidden()


def test_it_admin_retention_controls_require_dry_run_and_explicit_confirmation(page, make_account, monkeypatch):
    from app.routes import student_imports

    settings = get_settings().model_copy(update={"student_import_retention_days": 1})
    monkeypatch.setattr(student_imports, "get_settings", lambda: settings)
    account = make_account("IT Administrator")
    with SessionLocal() as db:
        batch = StudentImportBatch(
            status="PREVIEW",
            source_ciphertext=encrypt_sensitive_bytes(b"synthetic workbook bytes"),
            rows_ciphertext=encrypt_sensitive_bytes(b"[]"),
            row_count=1,
            valid_count=1,
            invalid_count=0,
            warning_count=0,
            existing_count=0,
            new_count=1,
            created_by=account["id"],
            created_at=datetime.now(UTC) - timedelta(days=2),
        )
        db.add(batch)
        db.commit()
        batch_id = batch.id

    login(page, account)
    page.get_by_role("button", name="Reference data", exact=True).click()
    status = page.locator("#student-import-retention-status")
    expect(status).to_contain_text("1 eligible payload")
    purge_button = page.get_by_role("button", name="Purge eligible payloads", exact=True)
    expect(purge_button).to_be_disabled()
    confirmation = page.get_by_label("I understand this permanently removes the retained import workbook and staged-row payloads.")
    confirmation.check()
    expect(purge_button).to_be_disabled()

    page.get_by_role("button", name="Preview eligible payloads", exact=True).click()
    expect(page.locator("#student-import-retention-result")).to_contain_text("Dry run complete: 1 encrypted payload")
    expect(confirmation).not_to_be_checked()
    expect(purge_button).to_be_disabled()
    with SessionLocal() as db:
        batch = db.get(StudentImportBatch, batch_id)
        assert batch.status == "PREVIEW" and batch.source_ciphertext and batch.rows_ciphertext

    confirmation.check()
    expect(purge_button).to_be_enabled()
    purge_button.click()
    expect(page.locator("#student-import-retention-result")).to_contain_text("1 encrypted payload(s) purged")
    with SessionLocal() as db:
        batch = db.get(StudentImportBatch, batch_id)
        assert batch.status == "EXPIRED" and batch.source_ciphertext is None and batch.rows_ciphertext is None
