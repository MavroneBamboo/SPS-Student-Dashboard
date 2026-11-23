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
    expect(page.get_by_role("status")).to_contain_text("An attendance session already exists for an overlapping class, date and period")


def test_operator_can_create_attendance_from_published_timetable(page, make_account, live_url):
    admin = make_account("IT Administrator")
    operator = make_account("Operator")

    def authenticate(account):
        response = page.request.post(
            live_url + "/api/v1/auth/login", data={"username": account["username"], "password": account["password"]}
        )
        assert response.status == 200
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    admin_headers = authenticate(admin)
    operator_headers = authenticate(operator)
    suffix = uuid4().hex[:8].upper()
    class_name = f"SCHED-{suffix}"
    academic_year = f"SCHED-{suffix}"

    def post(path, payload, headers):
        response = page.request.post(live_url + f"/api/v1/{path}", headers=headers, data=payload)
        assert response.status in (200, 201), f"{path}: {response.status} {response.text()}"
        return response.json()

    instructional_class = post("timetable/classes", {"code": f"C{suffix}", "name": f"Scheduled {suffix}"}, admin_headers)
    teacher = post("timetable/teachers", {"short_code": f"T{suffix}", "full_name": f"Teacher {suffix}"}, admin_headers)
    subject = post("timetable/subjects", {"code": f"S{suffix}", "name": f"Subject {suffix}"}, admin_headers)
    student = post(
        "students",
        {"pris_no": f"{class_name}-1", "name": "Scheduled Attendance Student", "class_name": class_name, "category": "OP"},
        operator_headers,
    )
    assert student["status"] == "ACTIVE"
    requirement = post(
        "timetable/lessons",
        {
            "academic_year": academic_year,
            "instructional_class_id": instructional_class["id"],
            "teacher_id": teacher["id"],
            "subject_id": subject["id"],
            "weekly_count": 1,
            "block_length": 1,
        },
        operator_headers,
    )
    post(
        "timetable/rules",
        {
            "academic_year": academic_year,
            "target_type": "CLASS",
            "target_id": instructional_class["id"],
            "effective_from": "2026-01-01",
            "effective_to": "2026-12-31",
            "rule": {},
        },
        admin_headers,
    )
    version = post(
        "timetable/versions",
        {
            "name": f"Attendance {suffix}",
            "academic_year": academic_year,
            "week_start": "2026-10-19",
            "class_ids": [instructional_class["id"]],
        },
        operator_headers,
    )
    version = post(
        f"timetable/versions/{version['id']}/placements",
        {
            "expected_revision": version["revision"],
            "lesson_requirement_id": requirement["id"],
            "weekday": "MON",
            "start_period": "P1",
            "period_count": 1,
        },
        operator_headers,
    )
    version = post(f"timetable/versions/{version['id']}/approve", {"expected_revision": version["revision"]}, admin_headers)
    version = post(f"timetable/versions/{version['id']}/publish", {"expected_revision": version["revision"]}, admin_headers)

    login(page, admin)
    page.get_by_role("button", name="Timetable / Schedule", exact=True).click()
    page.locator('[data-timetable-page="resources"]').click()
    page.locator('[data-resource-tab="classes"]').click()
    mapping_form = page.locator("#attendance-class-mapping-form")
    mapping_form.get_by_label("Student profile class", exact=True).fill(class_name)
    mapping_form.locator('select[name="instructional_class_id"]').select_option(str(instructional_class["id"]))
    mapping_form.get_by_role("button", name="Create attendance mapping", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Attendance class mapped")
    mappings = page.request.get(live_url + "/api/v1/student-reference/attendance-class-mappings", headers=admin_headers)
    assert mappings.status == 200
    assert next(row for row in mappings.json() if row["student_class_name"] == class_name)["active_students"] == 1

    page.get_by_role("button", name="Sign out", exact=True).click()
    login(page, operator)
    page.get_by_role("button", name="Attendance", exact=True).click()
    page.get_by_role("button", name="New session", exact=True).click()
    page.get_by_label("Session date", exact=True).fill("2026-10-19")
    page.locator("#scheduled-academic-year").fill(academic_year)
    page.get_by_role("button", name="Load published classes for date", exact=True).click()
    expect(page.locator("#scheduled-classes-summary")).to_contain_text("Published timetable for week of")
    page.locator("#scheduled-class-select").select_option(str(instructional_class["id"]))
    expect(page.get_by_label("Session class", exact=True)).to_have_value(class_name)
    expect(page.get_by_label("Expected students", exact=True)).to_have_value("1")
    page.get_by_role("button", name="Create session", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Created attendance session")

    sessions = page.request.get(live_url + "/api/v1/attendance/sessions", headers=operator_headers, params={"class_name": class_name})
    assert sessions.status == 200
    created = sessions.json()[0]
    assert created["timetable_version_id"] == version["id"]
    assert created["instructional_class_id"] == instructional_class["id"]
