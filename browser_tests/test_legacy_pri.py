import io
import json
import zipfile

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from playwright.sync_api import expect

from app.config import get_settings

KEY = bytes(range(16))


def _encrypted_member(value):
    iv = bytes(range(16, 32))
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(json.dumps(value).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(KEY), modes.CBC(iv)).encryptor()
    return iv + encryptor.update(padded) + encryptor.finalize()


def _valid_project():
    members = {
        "R01.bin": [{"Id": 0, "Name": "Synthetic Teacher", "Availability": ":".join(["1"] * 20)}],
        "R02.bin": [{"Id": 0, "Name": "Synthetic Subject"}],
        "R03.bin": [{"Id": 0, "Name": "Synthetic Class"}],
        "R04.bin": [
            {
                "Id": 0,
                "Teacher": "Synthetic Teacher",
                "Subject": "Synthetic Subject",
                "InstClass": "Synthetic Class",
                "Count": 2,
                "Length": 1,
            }
        ],
        "R05.bin": [
            {
                "Id": 0,
                "Teacher": "Synthetic Teacher",
                "Subject": "Synthetic Subject",
                "InstClass": "Synthetic Class",
                "DayOfWeek": "Mon",
                "Period": 1,
            },
            {
                "Id": 1,
                "Teacher": "Synthetic Teacher",
                "Subject": "Synthetic Subject",
                "InstClass": "Synthetic Class",
                "DayOfWeek": "Tue",
                "Period": 1,
            },
        ],
        "R06.bin": [],
    }
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, value in members.items():
            zipped.writestr(name, _encrypted_member(value))
    return archive.getvalue()


def _sign_in(page, account):
    page.get_by_label("Username", exact=True).fill(account["username"])
    page.get_by_label("Password", exact=True).fill(account["password"])
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.locator("#workspace")).to_be_visible()


def test_it_admin_can_validate_legacy_project_without_exposing_resource_names(page, make_account, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "legacy_pri_key_hex", KEY.hex())
    account = make_account("IT Administrator")
    _sign_in(page, account)

    page.get_by_role("button", name="Legacy timetable preflight", exact=True).click()
    expect(page.locator("#legacy-pri-panel")).to_be_visible()
    page.locator("#legacy-pri-form input[type=file]").set_input_files(
        {"name": "synthetic.pri", "mimeType": "application/octet-stream", "buffer": _valid_project()}
    )
    page.get_by_role("button", name="Validate project", exact=True).click()

    expect(page.locator("#legacy-pri-status")).to_contain_text("Validation completed")
    expect(page.locator("#legacy-pri-result")).to_be_visible()
    expect(page.locator("#legacy-pri-counts")).to_contain_text("teachers")
    expect(page.locator("#legacy-pri-periods")).to_contain_text("LUNCH")
    expect(page.locator("#legacy-pri-readiness")).to_contain_text("no data was imported")
    assert "Synthetic Teacher" not in page.locator("#legacy-pri-result").inner_text()
    assert "Synthetic Class" not in page.locator("#legacy-pri-result").inner_text()


def test_operator_does_not_see_legacy_project_preflight(page, make_account):
    account = make_account("Operator")
    _sign_in(page, account)
    expect(page.locator("#legacy-pri-nav")).to_be_hidden()
    page.get_by_role("button", name="Sign out", exact=True).click()

    superuser = make_account("Superuser")
    _sign_in(page, superuser)
    expect(page.locator("#legacy-pri-nav")).to_be_visible()
