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
    teacher_name="Synthetic Teacher",
    subject_name="Synthetic Subject",
    class_name="Synthetic Class",
    duplicate_slot=False,
    event_label=None,
    lunch_placeholder=False,
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
    if lunch_placeholder:
        members["R05.bin"].append(
            {
                "Id": len(members["R05.bin"]),
                "Teacher": "",
                "Subject": subject_name,
                "InstClass": class_name,
                "DayOfWeek": "Wed",
                "Period": 3,
            }
        )
    if event_label:
        members["R02.bin"].append({"Id": 1, "Name": event_label})
        members["R05.bin"].append(
            {
                "Id": len(members["R05.bin"]),
                "Teacher": "ALL",
                "Subject": event_label,
                "InstClass": class_name,
                "DayOfWeek": "Wed",
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
        event_label = "Synthetic Assembly " + suffix
        event_subject = client.post(
            "/api/v1/timetable/subjects",
            json={"code": "SYNTH-EV-" + suffix, "name": event_label},
            headers=headers,
        )
        assert event_subject.status_code == 201, event_subject.text
        fixed_event = client.post(
            "/api/v1/timetable/fixed-events",
            json={
                "academic_year": "2026",
                "label": event_label,
                "audience_type": "CLASS",
                "target_mode": "SELECTED",
                "target_ids": [instructional_class.json()["id"]],
                "slots": [{"weekday": "WED", "slot_code": "P1"}],
            },
            headers=headers,
        )
        assert fixed_event.status_code == 201, fixed_event.text
    _sign_in(page, account)

    page.get_by_role("button", name="Legacy timetable preflight", exact=True).click()
    expect(page.locator("#legacy-pri-panel")).to_be_visible()
    project_input = page.locator("#legacy-pri-form input[type=file]")
    project_input.set_input_files(
        {
            "name": "synthetic-invalid.pri",
            "mimeType": "application/octet-stream",
            "buffer": _valid_project(teacher_name, subject_name, class_name, duplicate_slot=True, event_label=event_label),
        }
    )
    page.get_by_role("button", name="Validate project", exact=True).click()

    expect(page.locator("#legacy-pri-status")).to_contain_text("Validation completed")
    expect(page.locator("#legacy-pri-result")).to_be_visible()
    expect(page.locator("#legacy-pri-counts")).to_contain_text("teachers")
    expect(page.locator("#legacy-pri-periods")).to_contain_text("LUNCH")
    expect(page.locator("#legacy-pri-issues")).to_contain_text("duplicate class slot: 1")
    expect(page.locator("#legacy-pri-issues")).to_contain_text("duplicate teacher slot: 1")
    expect(page.locator("#legacy-pri-issues")).to_contain_text("#3 conflicts with #1")
    expect(page.locator("#legacy-pri-issues")).to_contain_text("placement rows 3")
    assert teacher_name not in page.locator("#legacy-pri-result").inner_text()
    assert class_name not in page.locator("#legacy-pri-result").inner_text()

    page.locator("#legacy-pri-issues button[data-source='placement'][data-source-index='2']").first.click()
    expect(page.locator("#legacy-pri-source")).to_be_visible()
    expect(page.locator("#legacy-pri-source-placements tr.legacy-source-row-highlight")).to_contain_text(class_name)
    assert page.locator("#legacy-pri-source-placements tr.legacy-source-row-highlight").get_attribute("data-source-index") == "2"

    project_input.set_input_files(
        {
            "name": "synthetic.pri",
            "mimeType": "application/octet-stream",
            "buffer": _valid_project(teacher_name, subject_name, class_name, event_label=event_label, lunch_placeholder=True),
        }
    )
    page.get_by_role("button", name="Validate project", exact=True).click()
    expect(page.locator("#legacy-pri-issues")).to_contain_text("lunch entry requires review: 1")
    expect(page.locator("#legacy-pri-issues")).to_contain_text("whole school event mapping required: 1")
    expect(page.locator("#legacy-pri-readiness")).to_contain_text("Resolve these findings")

    page.get_by_role("button", name="Inspect source labels for mapping", exact=True).click()
    expect(page.locator("#legacy-pri-source")).to_be_visible()
    expect(page.locator("#legacy-pri-source-teachers")).to_contain_text(teacher_name)
    expect(page.locator("#legacy-pri-source-subjects")).to_contain_text(subject_name)
    expect(page.locator("#legacy-pri-source-classes")).to_contain_text(class_name)
    event_mapping = page.locator("#legacy-pri-map-events select[data-fixed-event-source-index='1']")
    expect(event_mapping).to_be_visible()
    event_mapping.select_option(value=str(fixed_event.json()["id"]))
    expect(page.locator("#legacy-pri-source-placements")).to_contain_text("Wed")
    lunch_review = page.locator("#legacy-pri-lunch-review")
    expect(lunch_review).to_be_visible()
    expect(lunch_review).to_contain_text("Synthetic Class")
    expect(lunch_review).to_contain_text("Wed")
    page.locator("#legacy-pri-import-form [name=name]").fill("Synthetic migrated week " + suffix)
    page.locator("#legacy-pri-import-form [name=academic_year]").fill("2026")
    page.locator("#legacy-pri-import-form [name=week_start]").fill("2026-10-26")
    page.get_by_role("button", name="Import as draft", exact=True).click()
    expect(page.locator("#notice")).to_contain_text("Review and confirm all 1 blank-teacher lunch placeholder rows")
    page.locator("#legacy-pri-lunch-review-rows input[data-lunch-placeholder-row='2']").check()
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
