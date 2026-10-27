from io import BytesIO
from uuid import uuid4

from openpyxl import Workbook
from playwright.sync_api import expect
from sqlalchemy import select

from app.crypto import decrypt_sensitive
from app.db import SessionLocal
from app.models import Student

from .test_browser import login

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _workbook(pris_no, *, name, ic_number):
    output = BytesIO()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Student Intake 2023"
    sheet.append(["S/N", "Pris No.", "CAT", "IC", "NAME", "INSTN CLASS", "STATUS", "STATUS EFFECTIVE"])
    sheet.append([1, pris_no, "OP", ic_number, name, "Browser Intake Class", "ACTIVE", "2026-01-02"])
    workbook.save(output)
    return output.getvalue()


def _upload(page, *, name, data):
    page.locator("#student-import-form input[name=workbook]").set_input_files({"name": name, "mimeType": XLSX, "buffer": data})
    page.get_by_role("button", name="Upload and preview", exact=True).click()


def test_operator_import_preview_create_and_explicit_update_preserves_blank_cells(page, make_account):
    account = make_account()
    pris_no = "BROWSER-IMPORT-" + uuid4().hex[:8].upper()
    login(page, account)
    page.get_by_role("button", name="Student profiles", exact=True).click()
    _upload(page, name="synthetic-intake.xlsx", data=_workbook(pris_no, name="Original import name", ic_number="SYNTH-BROWSER-IC"))
    expect(page.locator("#student-import-summary")).to_contain_text("1 rows; 1 valid; 0 invalid")
    page.get_by_role("button", name="Create new profiles only", exact=True).click()
    expect(page.locator("#student-import-summary")).to_contain_text("Status: COMMITTED")
    expect(page.get_by_role("status")).to_contain_text("1 created")

    _upload(page, name="updated-intake.xlsx", data=_workbook(pris_no, name="Updated import name", ic_number=None))
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
    login(page, account)
    page.get_by_role("button", name="Student profiles", exact=True).click()
    _upload(page, name="numeric-intake.xlsx", data=_workbook(pris_no, name="Numeric warning student", ic_number=12345678))
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
