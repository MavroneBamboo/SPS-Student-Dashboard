from playwright.sync_api import expect


def _sign_in(page, account):
    page.locator("#login-form input[name=username]").fill(account["username"])
    page.locator("#login-form input[name=password]").fill(account["password"])
    page.locator("#login-form").get_by_role("button", name="Sign in").click()
    expect(page.locator("#workspace")).to_be_visible()


def test_it_admin_manages_student_reference_catalogs(page, make_account):
    account = make_account("IT Administrator")
    _sign_in(page, account)
    page.get_by_role("button", name="Reference data").click()
    expect(page.locator("#reference-data-panel")).to_be_visible()

    category = "Browser Category"
    page.locator("#reference-catalog-create input[name=name]").fill(category)
    page.locator("#reference-catalog-create textarea[name=description]").fill("Synthetic browser catalog value")
    page.get_by_role("button", name="Add reference value").click()
    expect(page.locator("#reference-catalog-rows")).to_contain_text(category)

    year = "Browser AY 2026"
    page.get_by_role("tab", name="Academic years").click()
    expect(page.locator("#reference-catalog-create input[name=effective_from]")).to_be_visible()
    page.locator("#reference-catalog-create input[name=name]").fill(year)
    page.locator("#reference-catalog-create input[name=effective_from]").fill("2026-01-01")
    page.locator("#reference-catalog-create input[name=effective_to]").fill("2026-12-31")
    page.get_by_role("button", name="Add reference value").click()
    expect(page.locator("#reference-catalog-rows")).to_contain_text(year)
    expect(page.locator("#reference-catalog-rows")).to_contain_text("2026-12-31")


def test_superuser_can_see_reference_data_but_operator_cannot_manage_it(page, make_account):
    superuser = make_account("Superuser")
    _sign_in(page, superuser)
    expect(page.get_by_role("button", name="Reference data")).to_be_visible()
    page.get_by_role("button", name="Reference data").click()
    expect(page.locator("#reference-data-panel")).to_be_visible()
    page.get_by_role("button", name="Sign out").click()

    operator = make_account("Operator")
    _sign_in(page, operator)
    expect(page.get_by_role("button", name="Reference data")).to_be_hidden()
