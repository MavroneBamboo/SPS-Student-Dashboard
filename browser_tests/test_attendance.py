from uuid import uuid4

from playwright.sync_api import expect

from .test_browser import login, screenshot


def _students(page, live_url, account, count=2):
    auth = page.request.post(
        live_url + "/api/v1/auth/login", data={"username": account["username"], "password": account["password"]}
    ).json()
    headers = {"Authorization": f"Bearer {auth['access_token']}"}
    class_name = "BATT-" + uuid4().hex[:8].upper()
    students = []
    for index in range(count):
        response = page.request.post(
            live_url + "/api/v1/students",
            headers=headers,
            data={"pris_no": f"{class_name}-{index}", "name": f"Attendance Browser {index}", "class_name": class_name, "category": "OP"},
        )
        assert response.status == 201
        students.append(response.json())
    return headers, class_name, students


def _new_session(page, class_name):
    page.get_by_role("button", name="Attendance", exact=True).click()
    page.get_by_label("Session class filter", exact=True).fill(class_name)
    page.get_by_role("button", name="Search sessions", exact=True).click()
    page.get_by_role("button", name="New session", exact=True).click()
    page.get_by_label("Session class", exact=True).select_option(class_name)
    page.get_by_label("Session date", exact=True).fill("2026-10-26")
    page.get_by_role("button", name="Create session", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Created attendance session")


def _mark(page, pris_no, mark):
    page.get_by_label("Attendance Pris No.", exact=True).fill(pris_no)
    page.get_by_label("Attendance status", exact=True).select_option(mark)
    page.get_by_role("button", name="Save attendance", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Attendance saved")


def test_operator_attendance_create_lookup_record_correct_count_close_and_dashboard(page, make_account, live_url):
    account = make_account()
    _, class_name, students = _students(page, live_url, account)
    login(page, account)
    _new_session(page, class_name)
    expect(page.locator("#attendance-summary")).to_contain_text("roster 2 captured")
    expect(page.locator("#attendance-summary")).to_contain_text("0/2 recorded")
    page.get_by_role("button", name="Close session", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Attendance is incomplete")
    page.get_by_label("Eligible student identifier or name", exact=True).fill(students[0]["pris_no"])
    page.get_by_role("button", name="Find eligible students", exact=True).click()
    page.get_by_role("button", name=f"Select {students[0]['pris_no']}", exact=True).click()
    _mark(page, students[0]["pris_no"], "PRESENT")
    _mark(page, students[1]["pris_no"], "MISSING")
    expect(page.locator("#attendance-summary")).to_contain_text("1 marked missing")
    page.get_by_role("button", name=f"Correct {students[1]['pris_no']}", exact=True).click()
    page.get_by_label("Attendance status", exact=True).select_option("ABSENT")
    page.get_by_label("Correction reason", exact=True).fill("Verified against signed register")
    page.get_by_role("button", name="Save attendance", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Attendance saved")
    expect(page.locator("#attendance-record-rows")).to_contain_text("Verified against signed register")
    page.get_by_label("Revised expected count", exact=True).fill("3")
    page.get_by_label("Count change reason", exact=True).fill("Pending additional class confirmation")
    page.get_by_role("button", name="Update expected count", exact=True).click()
    expect(page.locator("#attendance-summary")).to_contain_text("2/3 recorded")
    page.get_by_label("Close incomplete attendance", exact=True).check()
    page.get_by_label("Closure reason", exact=True).fill("One student could not be confirmed before cutoff")
    page.get_by_role("button", name="Close session", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Attendance session closed")
    expect(page.locator("#attendance-summary")).to_contain_text("CLOSED")
    expect(page.locator("#attendance-write-panel")).to_be_hidden()
    screenshot(page, "operator-attendance-closed-review")
    page.get_by_role("button", name="Dashboard", exact=True).click()
    page.locator("#dashboard-filter").get_by_label("Class", exact=True).fill(class_name)
    page.get_by_role("button", name="Apply filters", exact=True).click()
    expect(page.locator("#metrics .metric").nth(2)).to_have_text("Missing attendance records1")
    page.get_by_role("button", name="Sign out", exact=True).click()
    expect(page.locator("#attendance-record-rows")).to_be_empty()
    expect(page.locator("#attendance-session-rows")).to_be_empty()


def test_duplicate_session_and_stale_attendance_require_reload(page, make_account, live_url):
    account = make_account()
    headers, class_name, students = _students(page, live_url, account, count=1)
    login(page, account)
    _new_session(page, class_name)
    sessions = page.request.get(live_url + "/api/v1/attendance/sessions", headers=headers, params={"class_name": class_name}).json()
    session = sessions[0]
    saved = page.request.post(
        live_url + f"/api/v1/attendance/sessions/{session['id']}/records",
        headers=headers,
        data={"pris_no": students[0]["pris_no"], "attendance_status": "PRESENT", "expected_session_version": 1},
    )
    assert saved.status == 201
    page.get_by_label("Attendance Pris No.", exact=True).fill(students[0]["pris_no"])
    page.get_by_role("button", name="Save attendance", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Attendance changed")
    expect(page.get_by_label("Attendance Pris No.", exact=True)).to_have_value(students[0]["pris_no"])
    page.get_by_role("button", name="Reload session", exact=True).click()
    expect(page.locator("#attendance-summary")).to_contain_text("1/1 recorded")
    page.get_by_role("button", name="New session", exact=True).click()
    page.get_by_label("Session class", exact=True).select_option(class_name)
    page.get_by_label("Session date", exact=True).fill("2026-10-26")
    page.get_by_role("button", name="Create session", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("A session already exists")
