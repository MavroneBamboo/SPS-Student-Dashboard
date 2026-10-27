from uuid import uuid4

from playwright.sync_api import expect
from sqlalchemy import select

from app.crypto import encrypt_sensitive
from app.db import SessionLocal
from app.models import Student, User

from .test_browser import login, screenshot


def _search(page, query):
    page.get_by_label("Search identifier or name", exact=True).fill(query)
    page.get_by_role("button", name="Search profiles", exact=True).click()


def _fill_profile(page, pris_no, name="Browser Profile Student"):
    page.get_by_label("Pris No.", exact=True).fill(pris_no)
    page.get_by_label("Student name", exact=True).fill(name)
    page.get_by_label("Student class", exact=True).fill("Browser Profile Class")
    page.get_by_label("Student category", exact=True).fill("OP")
    page.get_by_label("Status effective date", exact=True).fill("2026-10-01")
    page.get_by_label("Date of birth", exact=True).fill("2000-01-02")


def test_operator_profile_creation_duplicate_edit_history_dashboard_and_clear(page, make_account):
    account = make_account()
    pris_no = "BP-" + uuid4().hex[:10].upper()
    login(page, account)
    page.get_by_role("button", name="Student profiles", exact=True).click()
    profile_form = page.locator("#profile-form")
    _search(page, pris_no)
    expect(page.locator("#profile-rows")).to_contain_text("No student profiles")
    page.get_by_role("button", name="New student", exact=True).click()
    _fill_profile(page, pris_no.lower(), "Browser <img src=x onerror=alert(1)>")
    page.get_by_label("IC number", exact=True).fill("SYNTH-IC-BROWSER-1")
    profile_form.get_by_label("Academic year", exact=True).fill("2023")
    profile_form.get_by_label("Age in academic year", exact=True).fill("23")
    page.get_by_label("Next-of-kin NRIC", exact=True).fill("SYNTH-NRIC-BROWSER-1")
    page.get_by_label("Next-of-kin contact number", exact=True).fill("0000-1111")
    page.get_by_label("Language 1", exact=True).fill("Synthetic language")
    page.get_by_role("button", name="Save profile", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text(f"Saved student {pris_no}")
    expect(page.locator("#profile-version")).to_contain_text("Saved version 1")
    expect(page.get_by_label("IC number", exact=True)).to_have_value("SYNTH-IC-BROWSER-1")
    expect(profile_form.get_by_label("Academic year", exact=True)).to_have_value("2023")
    expect(page.get_by_label("Next-of-kin NRIC", exact=True)).to_have_value("SYNTH-NRIC-BROWSER-1")
    expect(page.locator("#profile-rows")).to_contain_text("Browser <img")
    assert page.locator("#profile-rows img").count() == 0
    assert page.get_by_label("Pris No.", exact=True).get_attribute("readonly") is not None
    page.get_by_role("button", name="New student", exact=True).click()
    _fill_profile(page, pris_no)
    page.get_by_role("button", name="Save profile", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Pris No. already exists")
    page.get_by_role("button", name="Close profile", exact=True).click()
    page.get_by_role("button", name=f"Open {pris_no}", exact=True).click()
    page.get_by_label("Next-of-kin contact number", exact=True).fill("")
    page.get_by_label("Next-of-kin NRIC", exact=True).fill("SYNTH-NRIC-BROWSER-2")
    page.get_by_label("Student name", exact=True).fill("Revised Browser Profile")
    page.get_by_label("Student status", exact=True).fill("INACTIVE")
    page.get_by_label("Status effective date", exact=True).fill("2026-10-02")
    page.get_by_role("button", name="Save profile", exact=True).click()
    expect(page.locator("#profile-version")).to_contain_text("Saved version 2")
    expect(page.locator("#profile-history tr")).to_have_count(2)
    expect(page.locator("#profile-history")).to_contain_text("2026-10-02")
    page.get_by_label("Date of birth", exact=True).fill("")
    page.get_by_role("button", name="Save profile", exact=True).click()
    expect(page.locator("#profile-version")).to_contain_text("Saved version 3")
    expect(page.locator("#profile-history tr")).to_have_count(2)
    with SessionLocal() as db:
        stored = db.scalar(select(Student).where(Student.pris_no == pris_no))
        assert stored.name_encrypted != "Revised Browser Profile" and stored.date_of_birth_encrypted is None
        assert stored.ic_number_encrypted != "SYNTH-IC-BROWSER-1"
        assert stored.next_of_kin_nric_encrypted != "SYNTH-NRIC-BROWSER-2"
        assert stored.next_of_kin_contact_encrypted is None
    screenshot(page, "operator-profile-edit-history")
    page.get_by_role("button", name="Dashboard", exact=True).click()
    page.get_by_label("Class", exact=True).fill("Browser Profile Class")
    page.get_by_role("button", name="Apply filters", exact=True).click()
    expect(page.locator("#metrics .metric").nth(0)).to_have_text("Active students0")
    page.get_by_role("button", name="Sign out", exact=True).click()
    expect(page.locator("#profile-rows")).to_be_empty()
    expect(page.locator("#profile-history")).to_be_empty()
    expect(page.get_by_label("Student name", exact=True)).to_have_value("")
    expect(page.get_by_label("Next-of-kin NRIC", exact=True)).to_have_value("")


def test_stale_profile_save_preserves_form_requires_reload_and_revoked_access_clears_data(page, make_account, live_url):
    account = make_account()
    pris_no = "CONFLICT-" + uuid4().hex[:8].upper()
    auth = page.request.post(
        live_url + "/api/v1/auth/login", data={"username": account["username"], "password": account["password"]}
    ).json()
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    created = page.request.post(
        live_url + "/api/v1/students",
        headers=headers,
        data={"pris_no": pris_no, "name": "Original", "class_name": "Profile Conflict", "category": "OP"},
    )
    assert created.status == 201
    profile = created.json()
    login(page, account)
    page.get_by_role("button", name="Student profiles", exact=True).click()
    _search(page, pris_no)
    page.get_by_role("button", name=f"Open {pris_no}", exact=True).click()
    expect(page.get_by_label("Student name", exact=True)).to_have_value("Original")
    winner = page.request.patch(
        live_url + f"/api/v1/students/{profile['id']}", headers=headers, data={"expected_version": 1, "name": "Other operator saved"}
    )
    assert winner.status == 200
    page.get_by_label("Student name", exact=True).fill("Unsaved local edit")
    page.get_by_role("button", name="Save profile", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("profile changed")
    expect(page.get_by_label("Student name", exact=True)).to_have_value("Unsaved local edit")
    page.get_by_role("button", name="Reload saved profile", exact=True).click()
    expect(page.get_by_label("Student name", exact=True)).to_have_value("Other operator saved")
    expect(page.locator("#profile-version")).to_contain_text("Saved version 2")
    with SessionLocal() as db:
        db.get(User, account["id"]).role = "Executive"
        db.commit()
    page.get_by_role("button", name="Search profiles", exact=True).click()
    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
    expect(page.get_by_role("status")).to_contain_text("Your access changed")
    expect(page.locator("#profile-rows")).to_be_empty()
    expect(page.get_by_label("Student name", exact=True)).to_have_value("")


def test_profile_pagination_and_navigation_controls(page, make_account):
    account = make_account()
    marker = "PAGE-" + uuid4().hex[:8].upper()
    with SessionLocal() as db:
        db.add_all(
            [
                Student(
                    pris_no=f"{marker}-{index:02}",
                    name_encrypted=encrypt_sensitive("Paged student"),
                    class_name="Page Class",
                    category="OP",
                    status="ACTIVE",
                    created_by=account["id"],
                )
                for index in range(26)
            ]
        )
        db.commit()
    login(page, account)
    page.get_by_role("button", name="Student profiles", exact=True).click()
    _search(page, marker)
    expect(page.locator("#profile-rows tr")).to_have_count(25)
    expect(page.get_by_role("button", name="Previous profiles", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Next profiles", exact=True).click()
    expect(page.locator("#profile-rows tr")).to_have_count(1)
    expect(page.get_by_role("button", name="Next profiles", exact=True)).to_be_disabled()
    page.get_by_role("button", name="Previous profiles", exact=True).click()
    expect(page.locator("#profile-rows tr")).to_have_count(25)
    expect(page.get_by_role("button", name="Previous profiles", exact=True)).to_be_disabled()
