import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test-sps-dashboard.db")
os.environ.setdefault("JWT_SECRET", "test-secret-that-is-long-enough")  # gitleaks:allow
os.environ.setdefault("BOOTSTRAP_PASSWORD", "test-bootstrap-password")

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import User
from app.security import hash_password


@pytest.fixture
def lesson_context():
    suffix = uuid4().hex[:10]
    password = "lesson-fixture-password"
    password_hash = hash_password(password)
    with TestClient(app) as client:
        headers = {}
        for key, role in (("admin", "IT Administrator"), ("operator", "Operator"), ("executive", "Executive"), ("superuser", "Superuser")):
            username = f"lesson-{key}-{suffix}"
            with SessionLocal() as db:
                db.add(User(username=username, password_hash=password_hash, role=role, must_change_password=False, is_active=True))
                db.commit()
            login = client.post("/api/v1/auth/login", json={"username": username, "password": password})
            assert login.status_code == 200
            headers[key] = {"Authorization": f"Bearer {login.json()['access_token']}"}
        references = {}
        for path, payload, key in (
            ("teachers", {"short_code": f"T{suffix}", "full_name": "Lesson Test Teacher"}, "teacher_id"),
            ("subjects", {"code": f"S{suffix}", "name": "Lesson Test Subject"}, "subject_id"),
            ("classes", {"code": f"C{suffix}", "name": "Lesson Test Class"}, "instructional_class_id"),
        ):
            created = client.post(f"/api/v1/timetable/{path}", json=payload, headers=headers["admin"])
            assert created.status_code == 201, created.text
            references[key] = created.json()["id"]
        yield client, headers, {"academic_year": "2026", "weekly_count": 4, "block_length": 2, **references}
