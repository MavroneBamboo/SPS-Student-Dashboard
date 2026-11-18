import io
import json
import zipfile
from uuid import uuid4

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi.testclient import TestClient
from playwright.sync_api import expect

from app.config import get_settings
from app.main import app

KEY = bytes(range(16))


def _encrypted_member(value):
    iv = bytes(range(16, 32))
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(json.dumps(value).encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(KEY), modes.CBC(iv)).encryptor()
    return iv + encryptor.update(padded) + encryptor.finalize()


def _valid_project(
    teacher_name="Synthetic Teacher", subject_name="Synthetic Subject", class_name="Synthetic Class", duplicate_slot=False
):
    members = {
        "R01.bin": [{"Id": 0, "Name": teacher_name, "Availability": ":".join(["1"] * 20)}],
        "R02.bin": [{"Id": 0, "Name": subject_name}],
        "R03.bin": [{"Id": 0, "Name": class_name}],
        "R04.bin": [
            {
                "Id": 0,
                "Teacher": teacher_name,
                "Subject": subject_name,
                "InstClass": class_name,
                "Count": 2,
                "Length": 1,
            }
        ],
        "R05.bin": [
            {
                "Id": 0,
                "Teacher": teacher_name,
                "Subject": subject_name,
                "InstClass": class_name,
                "DayOfWeek": "Mon",
                "Period": 1,
            },
            {
                "Id": 1,
                "Teacher": teacher_name,
                "Subject": subject_name,
                "InstClass": class_name,
                "DayOfWeek": "Tue",
                "Period": 1,
            },
        ],
        "R06.bin": [],
    }
    if duplicate_slot:
        members["R05.bin"].append(
            {
                "Id": 2,
                "Teacher": teacher_name,
                "Subject": subject_name,
                "InstClass": class_name,
                "DayOfWeek": "Mon",
                "Period": 1,
            }
        )
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
    suffix = uuid4().hex[:8]
    teacher_name = "Synthetic Teacher " + suffix
    subject_name = "Synthetic Subject " + suffix
    class_name = "Synthetic Class " + suffix
    with TestClient(app) as client:
        login = client.post("/api/v1/auth/login", json={"username": account["username"], "password": account["password"]})
        headers = {"Authorization": "Bearer " + login.json()["access_token"]}
        teacher = client.post(
            "/api/v1/timetable/teachers",
            json={"short_code": "SYNTH-LT-" + suffix, "full_name": teacher_name},
            headers=headers,
        )
        subject = client.post(
            "/api/v1/timetable/subjects",
            json={"code": "SYNTH-LS-" + suffix, "name": subject_name},
            headers=headers,
        )
        instructional_class = client.post(
            "/api/v1/timetable/classes",
            json={"code": "SYNTH-LC-" + suffix, "name": class_name},
            headers=headers,
        )
        assert teacher.status_code == subject.status_code == instructional_class.status_code == 201
        rule = client.post(
            "/api/v1/timetable/rules",
            json={
                "academic_year": "2026",
                "target_type": "CLASS",
                "target_id": instructional_class.json()["id"],
                "effective_from": "2026-01-01",
                "effective_to": "2026-12-31",
                "rule": {},
            },
            headers=headers,
        )
        assert rule.status_code == 201, rule.text
    _sign_in(page, account)

    page.get_by_role("button", name="Legacy timetable preflight", exact=True).click()
    expect(page.locator("#legacy-pri-panel")).to_be_visible()
    project_input = page.locator("#legacy-pri-form input[type=file]")
    project_input.set_input_files(
        {
            "name": "synthetic-invalid.pri",
            "mimeType": "application/octet-stream",
            "buffer": _valid_project(teacher_name, subject_name, class_name, duplicate_slot=True),
        }
    )
    page.get_by_role("button", name="Validate project", exact=True).click()

    expect(page.locator("#legacy-pri-status")).to_contain_text("Validation completed")
    expect(page.locator("#legacy-pri-result")).to_be_visible()
    expect(page.locator("#legacy-pri-counts")).to_contain_text("teachers")
    expect(page.locator("#legacy-pri-periods")).to_contain_text("LUNCH")
    expect(page.locator("#legacy-pri-issues")).to_contain_text("duplicate class slot: 1")
    expect(page.locator("#legacy-pri-issues")).to_contain_text("placement rows 3")
    assert teacher_name not in page.locator("#legacy-pri-result").inner_text()
    assert class_name not in page.locator("#legacy-pri-result").inner_text()

    project_input.set_input_files(
        {
            "name": "synthetic.pri",
            "mimeType": "application/octet-stream",
            "buffer": _valid_project(teacher_name, subject_name, class_name),
        }
    )
    page.get_by_role("button", name="Validate project", exact=True).click()
    expect(page.locator("#legacy-pri-issues")).to_contain_text("No reconciliation issues found")
    expect(page.locator("#legacy-pri-readiness")).to_contain_text("no data was imported")

    page.get_by_role("button", name="Inspect source labels for mapping", exact=True).click()
    expect(page.locator("#legacy-pri-source")).to_be_visible()
    expect(page.locator("#legacy-pri-source-teachers")).to_contain_text(teacher_name)
    expect(page.locator("#legacy-pri-source-subjects")).to_contain_text(subject_name)
    expect(page.locator("#legacy-pri-source-classes")).to_contain_text(class_name)
    expect(page.locator("#legacy-pri-source-placements")).to_contain_text("Mon")
    page.locator("#legacy-pri-import-form [name=name]").fill("Synthetic migrated week " + suffix)
    page.locator("#legacy-pri-import-form [name=academic_year]").fill("2026")
    page.locator("#legacy-pri-import-form [name=week_start]").fill("2026-10-26")
    page.get_by_role("button", name="Import as draft", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("Legacy timetable imported as draft")
    expect(page.locator("#timetable-panel")).to_be_visible()
    expect(page.locator("#timetable-version-rows")).to_contain_text("Synthetic migrated week " + suffix)
    expect(page.locator("#timetable-version-rows")).to_contain_text("DRAFT")
    page.get_by_role("button", name="Sign out", exact=True).click()
    expect(page.locator("#legacy-pri-source")).to_be_hidden()
    assert teacher_name not in page.locator("#legacy-pri-source").inner_text()
    assert not page.locator("#legacy-pri-source-placements").inner_text().strip()


def test_operator_does_not_see_legacy_project_preflight(page, make_account):
    account = make_account("Operator")
    _sign_in(page, account)
    expect(page.locator("#legacy-pri-nav")).to_be_hidden()
    page.get_by_role("button", name="Sign out", exact=True).click()

    superuser = make_account("Superuser")
    _sign_in(page, superuser)
    expect(page.locator("#legacy-pri-nav")).to_be_visible()
