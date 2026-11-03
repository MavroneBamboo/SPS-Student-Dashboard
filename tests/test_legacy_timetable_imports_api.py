import io
import json
import zipfile
from uuid import uuid4

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from fastapi.testclient import TestClient

from app.config import get_settings
from app.crypto import decrypt_sensitive_bytes
from app.db import SessionLocal
from app.main import app
from app.models import AuditEvent, LegacyTimetableImport, User
from app.security import hash_password

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
        "R01.bin": [{"Id": 0, "Name": "T1", "Availability": ":".join(["1"] * 25)}],
        "R02.bin": [{"Id": 0, "Name": "S1"}],
        "R03.bin": [{"Id": 0, "Name": "C1"}],
        "R04.bin": [{"Id": 0, "Teacher": "T1", "Subject": "S1", "InstClass": "C1", "Count": 1, "Length": 1}],
        "R05.bin": [
            {
                "Id": 0,
                "Teacher": "T1",
                "Subject": "S1",
                "InstClass": "C1",
                "DayOfWeek": "Mo",
                "Period": 1,
                "Note": unique_note,
            }
        ],
        "R06.bin": [],
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, value in members.items():
            archive.writestr(name, _encrypted_member(value))
    return buffer.getvalue()


def _auth_headers(role):
    suffix = uuid4().hex[:12]
    username = f"legacy-{role.lower().replace(' ', '-')}-{suffix}"
    password = "legacy-import-test-password"
    with SessionLocal() as db:
        db.add(User(username=username, password_hash=hash_password(password), role=role, must_change_password=False, is_active=True))
        db.commit()
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_it_admin_stages_encrypted_project_with_reconciliation_and_duplicate_guard(monkeypatch):
    monkeypatch.setenv("LEGACY_PRI_KEY_HEX", LEGACY_KEY.hex())
    get_settings.cache_clear()
    raw = _legacy_package()
    headers = _auth_headers("IT Administrator")
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/timetable/legacy-imports",
                content=raw,
                headers={**headers, "Content-Type": "application/octet-stream"},
            )
            assert response.status_code == 201, response.text
            body = response.json()
            assert body["status"] == "REVIEW_REQUIRED"
            assert body["counts"]["placements"] == 1
            assert body["import_ready"] is False
            assert body["issue_counts"]["legacy_period_mapping_required"] == 1
            source_rows = client.get(f"/api/v1/timetable/legacy-imports/{body['id']}/source-rows?kind=teachers", headers=headers)
            assert source_rows.status_code == 200
            assert source_rows.json()["items"][0]["Name"] == "T1"
            with SessionLocal() as db:
                staged = db.get(LegacyTimetableImport, body["id"])
                assert staged is not None
                assert staged.source_ciphertext != raw
                assert decrypt_sensitive_bytes(staged.source_ciphertext) == raw
            assert (
                client.post(
                    "/api/v1/timetable/legacy-imports",
                    content=raw,
                    headers={**headers, "Content-Type": "application/octet-stream"},
                ).status_code
                == 409
            )
            assert client.get("/api/v1/timetable/legacy-imports", headers=headers).json()[0]["id"] == body["id"]
            assert client.delete(f"/api/v1/timetable/legacy-imports/{body['id']}", headers=headers).status_code == 400
            assert client.delete(f"/api/v1/timetable/legacy-imports/{body['id']}?confirm=true", headers=headers).status_code == 204

        with SessionLocal() as db:
            assert db.get(LegacyTimetableImport, body["id"]) is None
            assert db.query(AuditEvent).filter_by(entity_type="legacy_timetable_import", entity_id=str(body["id"])).count() == 3
    finally:
        get_settings.cache_clear()


def test_operator_cannot_stage_legacy_project(monkeypatch):
    monkeypatch.setenv("LEGACY_PRI_KEY_HEX", LEGACY_KEY.hex())
    get_settings.cache_clear()
    headers = _auth_headers("Operator")
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/timetable/legacy-imports",
                content=_legacy_package(),
                headers={**headers, "Content-Type": "application/octet-stream"},
            )
            assert response.status_code == 403
            assert client.get("/api/v1/timetable/legacy-imports", headers=headers).status_code == 403
    finally:
        get_settings.cache_clear()


def test_legacy_staging_fails_closed_without_decryption_key(monkeypatch):
    monkeypatch.delenv("LEGACY_PRI_KEY_HEX", raising=False)
    get_settings.cache_clear()
    headers = _auth_headers("IT Administrator")
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/timetable/legacy-imports",
                content=_legacy_package(),
                headers={**headers, "Content-Type": "application/octet-stream"},
            )
            assert response.status_code == 503
    finally:
        get_settings.cache_clear()
