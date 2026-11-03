import os
import socket
import threading
import time
from urllib.error import URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen
from uuid import uuid4

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

os.environ.setdefault("JWT_SECRET", "browser-test-secret-that-is-long-enough-for-hs256")  # gitleaks:allow
os.environ.setdefault("LEGACY_PRI_KEY_HEX", "000102030405060708090a0b0c0d0e0f")  # gitleaks:allow

from app.db import SessionLocal
from app.main import app
from app.models import User
from app.security import hash_password


@pytest.fixture(scope="session")
def live_url():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        url = f"http://127.0.0.1:{listener.getsockname()[1]}"
        server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
        worker = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        worker.start()
        try:
            deadline = time.monotonic() + 15
            while True:
                try:
                    with urlopen(url + "/health/live", timeout=1) as response:  # noqa: S310
                        assert response.status == 200
                    break
                except (URLError, TimeoutError):
                    if time.monotonic() >= deadline:
                        pytest.fail("Browser test server did not become ready")
                    time.sleep(0.05)
            yield url
        finally:
            server.should_exit = True
            worker.join(timeout=10)
            assert not worker.is_alive(), "Browser server failed to shut down"


@pytest.fixture(scope="session")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(browser, live_url):
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.goto(live_url)
    yield page
    context.close()


def ensure_academic_year(page, headers, code, starts_on="2026-01-01", ends_on="2026-12-31"):
    current = urlsplit(page.url)
    origin = urlunsplit((current.scheme, current.netloc, "", "", ""))
    base = origin + "/api/v1/student-reference/academic-years"
    response = page.request.get(base, headers=headers)
    assert response.status == 200, response.text()
    row = next((item for item in response.json() if item["code"] == code.upper()), None)
    if row is None:
        result = page.request.post(
            base,
            headers=headers,
            data={"code": code, "label": code, "starts_on": starts_on, "ends_on": ends_on, "is_active": True},
        )
        assert result.status == 201, result.text()
        return result.json()
    if not row["is_active"] or row["starts_on"] != starts_on or row["ends_on"] != ends_on:
        result = page.request.patch(
            f"{base}/{row['id']}",
            headers=headers,
            data={"expected_version": row["version"], "starts_on": starts_on, "ends_on": ends_on, "is_active": True},
        )
        assert result.status == 200, result.text()
        return result.json()
    return row


@pytest.fixture
def make_account():
    def create(role="Operator", *, must_change=False):
        username = f"browser-{uuid4().hex[:12]}"
        password = "browser-test-start-password"
        with SessionLocal() as db:
            user = User(
                username=username, password_hash=hash_password(password), role=role, must_change_password=must_change, is_active=True
            )
            db.add(user)
            db.commit()
            return {"id": user.id, "username": username, "password": password}

    return create
