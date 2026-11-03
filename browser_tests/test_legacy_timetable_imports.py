import io
import json
import zipfile
from uuid import uuid4

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from playwright.sync_api import expect

LEGACY_KEY = bytes(range(16))


def _encrypted_member(value):
    iv = bytes(range(16, 32))
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(json.dumps(value).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(LEGACY_KEY), modes.CBC(iv)).encryptor()
    return iv + encryptor.update(padded) + encryptor.finalize()


def _legacy_package():
    unique_note = uuid4().hex
    members = {
        "R01.bin": [{"Id": 0, "Name": "T1", "FullName": "Test Teacher", "Adjunct": "N", "Availability": ":".join(["1"] * 25)}],
        "R02.bin": [{"Id": 0, "Name": "S1", "ShortName": "S1"}],
        "R03.bin": [{"Id": 0, "Name": "C1", "ShortName": "C1"}],
        "R04.bin": [{"Id": 0, "Teacher": "T1", "Subject": "S1", "InstClass": "C1", "Count": 1, "Length": 1}],
        "R05.bin": [{"Id": 0, "Teacher": "T1", "Subject": "S1", "InstClass": "C1", "DayOfWeek": "Mo", "Period": 1, "Note": unique_note}],
        "R06.bin": [],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, value in members.items():
            archive.writestr(name, _encrypted_member(value))
    return buffer.getvalue()


def test_it_admin_can_stage_and_review_a_legacy_project_in_the_browser(page, make_account, live_url):
    admin = make_account("IT Administrator")
    page.goto(live_url + "/ui/")
    page.get_by_label("Username", exact=True).fill(admin["username"])
    page.get_by_label("Password", exact=True).fill(admin["password"])
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("button", name="Timetable / Schedule", exact=True).click()
    page.get_by_role("button", name="Legacy import review", exact=True).click()
    page.locator("#legacy-pri-file").set_input_files(
        {"name": "review.pri", "mimeType": "application/octet-stream", "buffer": _legacy_package()}
    )
    page.get_by_role("button", name="Stage project for review", exact=True).click()
    expect(page.locator("#legacy-import-rows")).to_contain_text("REVIEW_REQUIRED")
    expect(page.locator("#legacy-import-issues")).to_contain_text("legacy_period_mapping_required")
    expect(page.locator("#legacy-source-rows")).to_contain_text('"Name":"T1"')


def test_operator_does_not_see_legacy_import_review(page, make_account, live_url):
    operator = make_account("Operator")
    page.goto(live_url + "/ui/")
    page.get_by_label("Username", exact=True).fill(operator["username"])
    page.get_by_label("Password", exact=True).fill(operator["password"])
    page.get_by_role("button", name="Sign in", exact=True).click()
    page.get_by_role("button", name="Timetable / Schedule", exact=True).click()
    expect(page.get_by_role("button", name="Legacy import review")).to_be_hidden()
