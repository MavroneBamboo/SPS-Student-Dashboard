from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from openpyxl import load_workbook
from playwright.sync_api import expect

from app.crypto import encrypt_sensitive
from app.db import SessionLocal
from app.models import AttendanceRecord, AttendanceRosterEntry, AttendanceSession, Student, User


def login(page, account):
    page.get_by_label("Username", exact=True).fill(account["username"])
    page.get_by_label("Password", exact=True).fill(account["password"])
    page.get_by_role("button", name="Sign in", exact=True).click()


def screenshot(page, name):
    Path("browser-artifacts").mkdir(exist_ok=True)
    page.screenshot(path=f"browser-artifacts/{name}.png", full_page=True)


def test_first_login_rotation_account_creation_role_change_disable_and_reload(page, make_account, live_url):
    expect(page.locator('link[rel="icon"]')).to_have_attribute("href", "/ui/sps-dashboard-logo.svg")
    logo = page.locator(".brand-logo")
    expect(logo).to_be_visible()
    assert page.evaluate("document.querySelector('.brand-logo').naturalWidth") == 128
    screenshot(page, "signin")
    page.set_viewport_size({"width": 390, "height": 844})
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    page.set_viewport_size({"width": 1280, "height": 900})

    account = make_account("Superuser", must_change=True)
    login(page, {**account, "password": "incorrect-password"})
    expect(page.get_by_role("status")).to_contain_text("Invalid username or password")
    login(page, account)
    expect(page.get_by_role("heading", name="Change your password", exact=True)).to_be_visible()
    expect(page.locator("#workspace")).to_be_hidden()
    page.get_by_label("Current password", exact=True).fill(account["password"])
    page.get_by_label("New password", exact=True).fill("browser-new-password")
    page.get_by_label("Confirm new password", exact=True).fill("different-new-password")
    page.get_by_role("button", name="Save new password").click()
    expect(page.get_by_role("status")).to_contain_text("do not match")
    page.get_by_label("Confirm new password", exact=True).fill("browser-new-password")
    page.get_by_role("button", name="Save new password").click()
    expect(page.get_by_role("heading", name="Intake and attendance overview", exact=True)).to_be_visible()
    expect(page.locator("#dashboard-nav")).to_have_attribute("aria-current", "page")
    for nav_id in ("dashboard-nav", "profiles-nav", "attendance-nav", "timetable-nav", "users-nav"):
        expect(page.locator(f"#{nav_id}")).to_be_visible()
    page.get_by_role("button", name="Student profiles", exact=True).click()
    expect(page.locator("#profiles-panel")).to_be_visible()
    expect(page.locator("#profiles-nav")).to_have_attribute("aria-current", "page")
    page.get_by_role("button", name="Attendance", exact=True).click()
    expect(page.locator("#attendance-panel")).to_be_visible()
    expect(page.locator("#attendance-nav")).to_have_attribute("aria-current", "page")
    page.get_by_role("button", name="Timetable / Schedule", exact=True).click()
    expect(page.locator("#timetable-board-page")).to_be_visible()
    expect(page.get_by_role("button", name="By teacher", exact=True)).to_be_visible()
    page.get_by_role("button", name="Classes & teachers", exact=True).click()
    expect(page.locator("#timetable-resources-page")).to_be_visible()
    page.get_by_role("button", name="Add teacher", exact=True).click()
    expect(page.locator("#timetable-teacher-form")).to_be_visible()
    page.get_by_role("button", name="Periods & rules", exact=True).click()
    expect(page.locator("#timetable-periods-page")).to_be_visible()
    page.get_by_role("button", name="Reports & export", exact=True).click()
    expect(page.locator("#timetable-reports-page")).to_be_visible()
    page.get_by_role("button", name="Dashboard", exact=True).click()
    expect(page.get_by_role("heading", name="Intake and attendance overview", exact=True)).to_be_visible()
    page.get_by_role("button", name="User administration", exact=True).click()
    expect(page.get_by_role("heading", name="User administration", exact=True)).to_be_visible()
    assert page.evaluate("Object.keys(localStorage).length + Object.keys(sessionStorage).length") == 0
    assert page.context.cookies() == []

    username = f"new-{uuid4().hex[:10]}"
    page.get_by_label("New username", exact=True).fill(username)
    page.get_by_label("Temporary password", exact=True).fill("browser-temporary-password")
    page.get_by_label("Assigned role", exact=True).select_option("Operator")
    page.get_by_role("button", name="Create account").click()
    expect(page.get_by_role("status")).to_contain_text(f"Created {username}")
    expect(page.get_by_label("Temporary password", exact=True)).to_have_value("")
    row = page.locator("#user-rows tr").filter(has_text=username)
    expect(row).to_contain_text("Required")
    row.get_by_label(f"Role for {username}", exact=True).select_option("Executive")
    row.get_by_role("button", name=f"Save {username}", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text(f"Updated {username}")
    expect(row.get_by_label(f"Role for {username}", exact=True)).to_have_value("Executive")
    row.get_by_label(f"Active for {username}", exact=True).uncheck()
    row.get_by_role("button", name=f"Save {username}", exact=True).click()
    expect(row.get_by_label(f"Active for {username}", exact=True)).not_to_be_checked()
    expect(page.get_by_role("status")).to_contain_text(f"Updated {username}")
    response = page.request.post(live_url + "/api/v1/auth/login", data={"username": username, "password": "browser-temporary-password"})
    assert response.status == 401
    screenshot(page, "superuser-administration")
    page.reload()
    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
    expect(page.locator("#user-rows")).to_be_empty()
    assert page.request.get(live_url + "/api/v1/auth/me").status == 401


def test_it_admin_named_account_reset_and_server_logout(page, make_account, live_url):
    admin = make_account("IT Administrator")
    login(page, admin)
    expect(page.get_by_role("heading", name="User administration", exact=True)).to_be_visible()
    expect(page.locator("#dashboard-nav")).to_be_hidden()
    assert "Superuser" not in page.get_by_label("Assigned role", exact=True).locator("option:not([hidden])").all_text_contents()
    username = f"it-created-{uuid4().hex[:10]}"
    page.get_by_label("New username", exact=True).fill(username)
    page.get_by_label("Temporary password", exact=True).fill("initial-temporary-password")
    page.get_by_role("button", name="Create account").click()
    row = page.locator("#user-rows tr").filter(has_text=username)
    expect(row).to_contain_text("Required")
    row.get_by_role("button", name=f"Reset password for {username}").click()
    expect(page.get_by_role("heading", name=f"Reset password for {username}")).to_be_visible()
    page.get_by_label("New temporary password", exact=True).fill("replacement-temporary-password")
    page.get_by_role("button", name="Set temporary password").click()
    expect(page.get_by_role("status")).to_contain_text("Temporary password set")
    assert (
        page.request.post(live_url + "/api/v1/auth/login", data={"username": username, "password": "initial-temporary-password"}).status
        == 401
    )
    replaced = page.request.post(live_url + "/api/v1/auth/login", data={"username": username, "password": "replacement-temporary-password"})
    assert replaced.status == 200 and replaced.json()["must_change_password"]
    with page.expect_response("**/api/v1/auth/logout") as logout:
        page.get_by_role("button", name="Sign out", exact=True).click()
    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
    assert logout.value.status == 204
    assert (
        page.request.get(live_url + "/api/v1/auth/me", headers={"Authorization": logout.value.request.headers["authorization"]}).status
        == 401
    )


def test_session_management_revokes_only_the_selected_login(page, make_account, live_url):
    account_data = make_account("Operator")
    login(page, account_data)
    second_login = page.request.post(
        live_url + "/api/v1/auth/login", data={"username": account_data["username"], "password": account_data["password"]}
    )
    assert second_login.status == 200
    second_token = {"Authorization": f"Bearer {second_login.json()['access_token']}"}

    page.get_by_role("button", name="Active sessions", exact=True).click()
    session_rows = page.locator("#session-rows tr")
    expect(session_rows).to_have_count(2)
    other_row = session_rows.filter(has_text="Other session")
    assert other_row.count() == 1
    other_row.get_by_role("button", name="Revoke this session", exact=True).click()
    expect(session_rows).to_have_count(1)
    expect(session_rows).to_contain_text("Current browser")
    assert page.request.get(live_url + "/api/v1/auth/me", headers=second_token).status == 401
    expect(page.get_by_role("status")).to_contain_text("Session revoked")
    page.get_by_role("button", name="Back to workspace", exact=True).click()
    expect(page.get_by_role("heading", name="Intake and attendance overview", exact=True)).to_be_visible()


@pytest.mark.parametrize("role", ["Operator", "Executive"])
def test_live_dashboard_filters_refresh_and_safe_text_for_each_operational_role(page, make_account, role):
    account = make_account(role)
    class_name = f"C-{uuid4().hex[:6]} <img src=x onerror=alert(1)>"
    with SessionLocal() as db:
        student = Student(
            pris_no=f"B-{uuid4().hex[:12]}",
            name_encrypted=encrypt_sensitive("Browser Test Student"),
            class_name=class_name,
            category="OP",
            status="ACTIVE",
            created_by=account["id"],
        )
        session = AttendanceSession(
            session_date=date(2026, 10, 20),
            session_type="MORNING",
            class_name=class_name,
            expected_count=1,
            created_by=account["id"],
            roster_snapshot_state="CAPTURED",
        )
        db.add_all([student, session])
        db.flush()
        student_id = student.id
        db.add(
            AttendanceRosterEntry(
                session_id=session.id,
                student_id=student.id,
                pris_no_snapshot=student.pris_no,
                student_name_encrypted=student.name_encrypted,
                student_status=student.status,
                created_by=account["id"],
            )
        )
        db.add(
            AttendanceRecord(
                session_id=session.id,
                student_id=student.id,
                attendance_status="PRESENT",
                created_by=account["id"],
                updated_by=account["id"],
            )
        )
        student_id = student.id
        db.commit()

    login(page, account)
    expect(page.get_by_role("heading", name="Intake and attendance overview")).to_be_visible()
    expect(page.locator("#users-nav")).to_be_hidden()
    page.locator("#dashboard-filter").get_by_label("Class", exact=True).fill(class_name)
    page.get_by_label("Attendance from", exact=True).fill("2026-10-20")
    page.get_by_label("Attendance to", exact=True).fill("2026-10-20")
    page.get_by_role("button", name="Apply filters").click()
    expect(page.locator("#metrics .metric").nth(0)).to_have_text("Matching profiles1")
    expect(page.locator("#metrics .metric").nth(1)).to_have_text("Active students1")
    expect(page.locator("#metrics .metric").nth(2)).to_have_text("Attendance100%")
    expect(page.locator("#attendance-trend")).to_contain_text(class_name)
    assert page.locator("#class-counts img").count() == 0
    with SessionLocal() as db:
        db.get(Student, student_id).status = "INACTIVE"
        db.commit()
    page.get_by_role("button", name="Refresh data").click()
    expect(page.locator("#metrics .metric").nth(0)).to_have_text("Matching profiles1")
    expect(page.locator("#metrics .metric").nth(1)).to_have_text("Active students0")
    screenshot(page, role.lower().replace(" ", "-") + "-dashboard")
    page.get_by_role("button", name="Sign out", exact=True).click()
    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
    expect(page.locator("#metrics")).to_be_empty()
    expect(page.locator("#attendance-trend")).to_be_empty()


def test_monthly_attendance_download_from_dashboard(page, make_account, tmp_path):
    account = make_account("Operator")
    class_name = f"MONTHLY-{uuid4().hex[:8]}"
    session_date = date.today()
    with SessionLocal() as db:
        student = Student(
            pris_no=f"B-{uuid4().hex[:12]}",
            name_encrypted=encrypt_sensitive("Monthly Browser Student"),
            class_name=class_name,
            category="OP",
            status="ACTIVE",
            created_by=account["id"],
        )
        session = AttendanceSession(
            session_date=session_date,
            session_type="MORNING",
            class_name=class_name,
            expected_count=1,
            created_by=account["id"],
            roster_snapshot_state="CAPTURED",
        )
        db.add_all([student, session])
        db.flush()
        db.add(
            AttendanceRosterEntry(
                session_id=session.id,
                student_id=student.id,
                pris_no_snapshot=student.pris_no,
                student_name_encrypted=student.name_encrypted,
                student_status=student.status,
                created_by=account["id"],
            )
        )
        db.add(
            AttendanceRecord(
                session_id=session.id,
                student_id=student.id,
                attendance_status="PRESENT",
                created_by=account["id"],
                updated_by=account["id"],
            )
        )
        student_id = student.id
        db.commit()

    with SessionLocal() as db:
        moved = db.get(Student, student_id)
        moved.name_encrypted = encrypt_sensitive("Renamed Browser Student")
        moved.class_name = "BROWSER-TRANSFERRED"
        moved.status = "INACTIVE"
        db.commit()

    login(page, account)
    expect(page.get_by_role("heading", name="Intake and attendance overview")).to_be_visible()
    report = page.locator("#monthly-attendance-report")
    report.locator("input[name='class_name']").fill(class_name)
    report.locator("input[name='month']").fill(session_date.strftime("%Y-%m"))
    with page.expect_download() as download_info:
        report.get_by_role("button", name="Download Excel register").click()
    download = download_info.value
    assert class_name.replace(" ", "_") in download.suggested_filename
    target = tmp_path / download.suggested_filename
    download.save_as(target)
    sheet = load_workbook(target, data_only=True).active
    attendance_column = 4 + (session_date.day - 1) * 2
    assert sheet.cell(4, attendance_column).value == "AM"
    assert sheet.cell(5, attendance_column).value == "P"
    assert sheet.cell(5, 1).value == "ACTIVE"
    assert sheet.cell(5, 2).value.startswith("B-")
    assert sheet.cell(5, 3).value == "Monthly Browser Student"


def test_deactivated_account_is_signed_out_and_sensitive_workspace_cleared(page, make_account):
    account = make_account()
    login(page, account)
    expect(page.get_by_role("heading", name="Intake and attendance overview")).to_be_visible()
    with SessionLocal() as db:
        db.get(User, account["id"]).is_active = False
        db.commit()
    page.get_by_role("button", name="Refresh data").click()
    expect(page.get_by_role("status")).to_contain_text("Your session ended")
    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
    expect(page.locator("#metrics")).to_be_empty()


def test_expiry_timer_clears_in_memory_session(page, make_account):
    account = make_account()

    def shorten_response(route):
        response = route.fetch()
        payload = response.json()
        route.fulfill(response=response, json={**payload, "expires_in": 1})

    page.route("**/api/v1/auth/login", shorten_response)
    login(page, account)
    expect(page.get_by_role("heading", name="Intake and attendance overview")).to_be_visible()
    expect(page.get_by_role("status")).to_contain_text("Your session expired", timeout=5000)
    expect(page.locator("#metrics")).to_be_empty()


def test_late_response_from_signed_out_session_cannot_restore_dashboard(page, make_account):
    account = make_account()
    with page.expect_response("**/api/v1/reports/dashboard?*") as dashboard_response:
        login(page, account)
    data = dashboard_response.value.json()
    expect(page.get_by_role("heading", name="Intake and attendance overview")).to_be_visible()
    # Simulate a transport that delivers an already fetched response after abort.
    page.evaluate("""() => {
        const original = window.fetch;
        window.fetch = (url, options) => String(url).includes('/reports/dashboard?')
            ? new Promise(resolve => { window.lateResponse = resolve; }) : original(url, options);
    }""")
    page.get_by_role("button", name="Refresh data").click()
    page.wait_for_function("typeof window.lateResponse === 'function'")
    page.get_by_role("button", name="Sign out", exact=True).click()
    page.evaluate("payload => window.lateResponse(new Response(JSON.stringify(payload), {status: 200}))", data)
    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
    expect(page.locator("#metrics")).to_be_empty()
    expect(page.locator("#attendance-trend")).to_be_empty()
