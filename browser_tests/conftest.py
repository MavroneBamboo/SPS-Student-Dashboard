import socket
import threading
import time
from datetime import UTC, datetime
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

import pytest
import uvicorn
from playwright.sync_api import sync_playwright

from app.config import get_settings
from app.db import SessionLocal
from app.main import app
from app.models import SetupState, StudentReferenceValue, User
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


@pytest.fixture
def make_account():
    def create(role="Operator", *, must_change=False):
        username = f"browser-{uuid4().hex[:12]}"
        password = "browser-test-start-password"
        with SessionLocal() as db:
            settings = get_settings()
            bootstrap = db.query(User).filter(User.username == settings.bootstrap_username).first()
            setup = db.get(SetupState, 1)
            if bootstrap is not None and setup is not None:
                setup.completed = True
                setup.completed_at = datetime.now(UTC)
                setup.completed_by = bootstrap.id
            for catalog_type, name, normalized_key in (
                ("CATEGORY", "OP", "op"),
                ("ACADEMIC_YEAR", "2023", "2023"),
                ("INSTITUTION", "Synthetic Institution", "synthetic institution"),
            ):
                if db.query(StudentReferenceValue.id).filter_by(catalog_type=catalog_type, normalized_key=normalized_key).first() is None:
                    db.add(StudentReferenceValue(catalog_type=catalog_type, name=name, normalized_key=normalized_key))
            user = User(
                username=username, password_hash=hash_password(password), role=role, must_change_password=must_change, is_active=True
            )
            db.add(user)
            db.commit()
            return {"id": user.id, "username": username, "password": password}

    return create
