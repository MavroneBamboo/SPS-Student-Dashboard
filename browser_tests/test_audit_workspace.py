import re
from uuid import uuid4

from playwright.sync_api import expect


def login(page, account):
    page.get_by_label("Username", exact=True).fill(account["username"])
    page.get_by_label("Password", exact=True).fill(account["password"])
    page.get_by_role("button", name="Sign in", exact=True).click()


def test_it_administrator_can_filter_and_review_read_only_audit_events(page, make_account):
    admin = make_account("IT Administrator")
    login(page, admin)
    expect(page.get_by_role("heading", name="User administration", exact=True)).to_be_visible()
    expect(page.locator("#audit-nav")).to_be_visible()

    new_username = f"audit-target-{uuid4().hex[:8]}"
    create_form = page.locator("#create-user-form")
    create_form.get_by_label("New username", exact=True).fill(new_username)
    create_form.get_by_label("Temporary password", exact=True).fill("audit-target-temporary-password")
    create_form.get_by_label("Assigned role", exact=True).select_option("Operator")
    create_form.get_by_role("button", name="Create account").click()
    expect(page.get_by_role("status")).to_contain_text(f"Created {new_username}")

    page.get_by_role("button", name="Audit log", exact=True).click()
    expect(page.locator("#audit-title")).to_be_visible()
    audit_filter = page.locator("#audit-filter")
    audit_filter.get_by_label("Action", exact=True).fill("user.created")
    audit_filter.get_by_label("Entity type", exact=True).fill("user")
    audit_filter.get_by_label("Actor ID", exact=True).fill(str(admin["id"]))
    audit_filter.get_by_role("button", name="Apply filters").click()

    event_row = page.locator("#audit-rows tr").filter(has_text=new_username)
    expect(event_row).to_have_count(1)
    expect(event_row).to_contain_text(admin["username"])
    expect(event_row).to_contain_text("user.created")
    request_id = event_row.locator("td.audit-request-id")
    expect(request_id).to_have_text(re.compile(r"^[0-9a-f]{32}$"))
    event_row.get_by_text("View details", exact=True).click()
    expect(event_row.locator("pre.audit-details")).to_contain_text(new_username)
    expect(event_row.locator("pre.audit-details")).not_to_contain_text("audit-target-temporary-password")


def test_operator_does_not_see_audit_navigation(page, make_account):
    operator = make_account("Operator")
    login(page, operator)
    expect(page.locator("#dashboard-panel")).to_be_visible()
    expect(page.locator("#audit-nav")).to_be_hidden()


def test_superuser_can_open_audit_workspace(page, make_account):
    superuser = make_account("Superuser")
    login(page, superuser)
    expect(page.locator("#audit-nav")).to_be_visible()
    page.get_by_role("button", name="Audit log", exact=True).click()
    expect(page.locator("#audit-title")).to_be_visible()
