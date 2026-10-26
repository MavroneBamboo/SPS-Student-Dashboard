from uuid import uuid4

from playwright.sync_api import expect


def test_operator_amend_4_up_add_move_lock_and_it_approves_complete_draft(page, make_account, live_url):
    admin = make_account("IT Administrator")
    login = page.request.post(live_url + "/api/v1/auth/login", data={"username": admin["username"], "password": admin["password"]})
    assert login.status == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    suffix = uuid4().hex[:8].upper()
    availability = {day: ["P1", "P2", "P3", "P4"] for day in ("MON", "TUE", "WED", "THU", "FRI")}

    def create(path, payload):
        response = page.request.post(live_url + path, data=payload, headers=headers)
        assert response.status == 201, response.text()
        return response.json()

    teacher = create(
        "/api/v1/timetable/teachers", {"short_code": f"T{suffix}", "full_name": "Browser Timetable Teacher", "availability": availability}
    )
    subject = create("/api/v1/timetable/subjects", {"code": f"S{suffix}", "name": "Browser Timetable Subject"})
    class_item = create("/api/v1/timetable/classes", {"code": f"C{suffix}", "name": "Browser Timetable Class"})
    rule = create(
        "/api/v1/timetable/rules",
        {
            "academic_year": "2026",
            "target_type": "CLASS",
            "target_id": class_item["id"],
            "effective_from": "2026-01-01",
            "rule": {
                "schema_version": 1,
                "max_lessons_per_day": 4,
                "allowed_days": ["MON", "TUE", "WED", "THU", "FRI"],
                "allowed_periods": ["P1", "P2", "P3", "P4"],
            },
        },
    )
    assert rule["target_id"] == class_item["id"]
    create(
        "/api/v1/timetable/lessons",
        {
            "academic_year": "2026",
            "instructional_class_id": class_item["id"],
            "teacher_id": teacher["id"],
            "subject_id": subject["id"],
            "weekly_count": 3,
            "block_length": 2,
        },
    )

    page.goto(live_url + "/ui/")
    page.get_by_label("Username", exact=True).fill(admin["username"])
    page.get_by_label("Password", exact=True).fill(admin["password"])
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_role("heading", name="User administration", exact=True)).to_be_visible()
    page.get_by_role("button", name="Timetable / Schedule", exact=True).click()
    expect(page.locator("#timetable-resource-summary")).to_contain_text("teacher profiles")
    page.get_by_role("button", name="Create weekly draft", exact=True).click()
    form = page.locator("#timetable-create-form")
    form.get_by_label("Draft name", exact=True).fill("Browser Amend 4-up")
    form.get_by_label("Academic year", exact=True).fill("2026")
    form.get_by_label("Week starting Monday", exact=True).fill("2026-10-26")
    class_select = form.locator('select[name="class_ids"]')
    expect(class_select).to_be_visible()
    class_option = class_select.locator(f'option[value="{class_item["id"]}"]')
    expect(class_option).to_be_attached()
    class_select.select_option(str(class_item["id"]))
    form.get_by_role("button", name="Create draft", exact=True).click()
    expect(page.get_by_role("heading", name="C" + suffix + " · Browser Timetable Class", exact=True)).to_be_visible()
    expect(page.locator(".amend-grid .lunch-cell").first).to_contain_text("Lunch")
    expect(page.locator("#timetable-pending")).to_contain_text("Browser Timetable Subject")
    expect(page.locator("#timetable-pending")).to_contain_text("Browser Timetable Class")
    assert page.locator(".amend-grid thead tr").inner_text().index("P2") < page.locator(".amend-grid thead tr").inner_text().index("Lunch")
    assert page.locator(".amend-grid thead tr").inner_text().index("Lunch") < page.locator(".amend-grid thead tr").inner_text().index("P3")

    page.get_by_role("button", name=f"Add lesson to C{suffix} MON Period 1", exact=True).click()
    placement_form = page.locator("#timetable-placement-form")
    try:
        expect(placement_form).to_be_visible()
    except AssertionError as error:
        raise AssertionError(f"Lesson form did not open; UI status: {page.get_by_role('status').inner_text()}") from error
    expect(page.get_by_role("heading", name="Add lesson block", exact=True)).to_be_visible()
    page.get_by_role("button", name="Save lesson", exact=True).click()
    expect(page.locator(".amend-grid")).to_contain_text(f"S{suffix} · T{suffix}")
    page.get_by_role("button", name=f"C{suffix} MON Period 1 S{suffix} · T{suffix}", exact=True).click()
    page.locator('#timetable-placement-form select[name="start_period"]').select_option("P3")
    page.get_by_role("button", name="Save lesson", exact=True).click()
    expect(page.get_by_role("button", name=f"C{suffix} MON Period 3 S{suffix} · T{suffix}", exact=True)).to_be_visible()
    page.get_by_role("button", name="Generate timetable", exact=True).click()
    expect(page.locator("#timetable-generation-summary")).to_contain_text("Generation complete")
    expect(page.locator("#timetable-pending")).to_contain_text("All weekly lesson requirements are placed")
    page.get_by_role("button", name=f"C{suffix} MON Period 3 S{suffix} · T{suffix}", exact=True).click()
    page.get_by_role("button", name="Lock lesson", exact=True).click()
    expect(page.locator(".amend-grid")).to_contain_text("locked")
    page.get_by_role("button", name="Approve complete draft", exact=True).click()
    expect(page.locator("#timetable-version-detail")).to_contain_text("APPROVED")
    assert page.locator("#timetable-pending").inner_text().find("All weekly lesson requirements are placed") >= 0


def test_it_creates_teacher_class_cluster_period_rule_and_lesson_in_workspace(page, make_account, live_url):
    admin = make_account("IT Administrator")
    page.goto(live_url + "/ui/")
    page.get_by_label("Username", exact=True).fill(admin["username"])
    page.get_by_label("Password", exact=True).fill(admin["password"])
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("button", name="Timetable / Schedule", exact=True).click()
    expect(page.locator("#timetable-setup")).to_be_visible()
    expect(page.locator("#timetable-resource-summary")).to_contain_text("teacher profiles")
    page.get_by_text("Scheduling setup: teachers, subjects, classes, rules and periods", exact=True).click()
    expect(page.locator("#timetable-setup")).to_have_attribute("open", "")
    suffix = uuid4().hex[:8].upper()

    page.get_by_label("Teacher code", exact=True).fill(f"T{suffix}")
    page.get_by_label("Teacher name", exact=True).fill("Setup Workspace Teacher")
    page.get_by_role("button", name="Create teacher", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Teacher profile created")
    page.get_by_label("Subject code", exact=True).fill(f"S{suffix}")
    page.get_by_label("Subject name", exact=True).fill("Setup Workspace Subject")
    page.get_by_role("button", name="Create subject", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Subject created")
    page.get_by_label("Class code", exact=True).fill(f"C{suffix}")
    page.get_by_label("Class name", exact=True).fill("Setup Workspace Class")
    page.get_by_role("button", name="Create class", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Instructional class created")
    page.get_by_label("Cluster code", exact=True).fill(f"G{suffix}")
    page.get_by_label("Cluster name", exact=True).fill("Setup Workspace Cluster")
    page.get_by_role("button", name="Create cluster", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Class cluster created")
    member_form = page.locator("#timetable-cluster-member-form")
    cluster_select = member_form.locator('select[name="cluster_id"]')
    class_member_select = member_form.locator('select[name="instructional_class_id"]')
    expect(cluster_select.locator("option").filter(has_text=f"G{suffix} · Setup Workspace Cluster")).to_be_attached()
    expect(class_member_select.locator("option").filter(has_text=f"C{suffix} · Setup Workspace Class")).to_be_attached()
    cluster_select.select_option(label=f"G{suffix} · Setup Workspace Cluster")
    class_member_select.select_option(label=f"C{suffix} · Setup Workspace Class")
    page.get_by_role("button", name="Add class to cluster", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Class added to cluster")
    period_form = page.locator("#timetable-period-form")
    period_form.locator('select[name="target_id"]').select_option(label=f"C{suffix} · Setup Workspace Class")
    period_form.locator('select[name="slot_code"]').select_option("P1")
    page.get_by_label("Display label", exact=True).fill("Early start")
    page.get_by_label("Starts at", exact=True).fill("08:00")
    page.get_by_label("Ends at", exact=True).fill("09:00")
    page.get_by_role("button", name="Save period override", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Period override saved")
    rule_form = page.locator("#timetable-rule-form")
    rule_form.get_by_label("Academic year", exact=True).fill("2026")
    rule_form.locator('select[name="target_type"]').select_option("CLASS")
    rule_form.locator('select[name="target_id"]').select_option(label=f"C{suffix} · Setup Workspace Class")
    rule_form.get_by_label("Effective from", exact=True).fill("2026-01-01")
    page.get_by_role("button", name="Save scheduling rule", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Scheduling rule saved")
    lesson_form = page.locator("#timetable-lesson-form")
    lesson_form.get_by_label("Academic year", exact=True).fill("2026")
    lesson_form.locator('select[name="instructional_class_id"]').select_option(label=f"C{suffix} · Setup Workspace Class")
    lesson_form.locator('select[name="teacher_id"]').select_option(label=f"T{suffix} · Setup Workspace Teacher")
    lesson_form.locator('select[name="subject_id"]').select_option(label=f"S{suffix} · Setup Workspace Subject")
    page.get_by_role("button", name="Save lesson requirement", exact=True).click()
    expect(page.get_by_role("status")).to_contain_text("Weekly lesson requirement saved")
    expect(page.locator("#timetable-resource-summary")).to_contain_text("clusters")
    expect(page.locator("#timetable-period-rows")).to_contain_text("Early start")
