"""
E2E test fixtures.

Requires the test MongoDB to be running:
  docker compose -f docker-compose.test.yml up -d

Run tests:
  pytest tests/e2e -m e2e -s
"""
import os
import threading
import time

import bcrypt
import pytest
import uvicorn
from motor.motor_asyncio import AsyncIOMotorClient
from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright

# ── Test environment ──────────────────────────────────────────────────────────

TEST_MONGO_URI = "mongodb://localhost:27018"
TEST_MONGO_DB = "signals_test"
TEST_USER_EMAIL = "free@test.signals"
TEST_USER_PASSWORD = "testpassword123"
APP_PORT = 18888
APP_BASE_URL = f"http://localhost:{APP_PORT}"

# Override settings before importing the app
os.environ["MONGO_URI"] = TEST_MONGO_URI
os.environ["MONGO_DB"] = TEST_MONGO_DB
os.environ["JWT_SECRET"] = "e2e-test-secret-do-not-use-in-prod"
os.environ["JWT_EXPIRE_MINUTES"] = "60"
os.environ["MANDATORY_EMAIL_VERIFICATION"] = "false"
os.environ.setdefault("LLM_API_KEY", "test-key")


# ── App server fixture ────────────────────────────────────────────────────────

class _UvicornThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self._server: uvicorn.Server | None = None

    def run(self):
        from src.main import app
        config = uvicorn.Config(app, host="127.0.0.1", port=APP_PORT, log_level="warning")
        self._server = uvicorn.Server(config)
        self._server.run()

    def stop(self):
        if self._server:
            self._server.should_exit = True


@pytest.fixture(scope="session")
def live_server():
    """Start the FastAPI app in a background thread for the whole test session."""
    thread = _UvicornThread()
    thread.start()
    # Wait until the server is ready
    import httpx
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            httpx.get(f"{APP_BASE_URL}/health", timeout=1)
            break
        except Exception:
            time.sleep(0.3)
    else:
        raise RuntimeError("Test server did not start in time")
    yield APP_BASE_URL
    thread.stop()


# ── Test user fixture ─────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def test_user(live_server):
    """
    Ensure a FREE test user exists in the test MongoDB.
    Created once per session; dropped after.
    """
    import asyncio
    from beanie import init_beanie
    from src.models.user import User

    async def _setup():
        client = AsyncIOMotorClient(TEST_MONGO_URI)
        db = client[TEST_MONGO_DB]
        await init_beanie(database=db, document_models=[User])
        # Clean slate
        await User.find(User.email == TEST_USER_EMAIL).delete()
        hashed = bcrypt.hashpw(TEST_USER_PASSWORD.encode(), bcrypt.gensalt()).decode()
        user = User(
            email=TEST_USER_EMAIL,
            hashed_password=hashed,
            is_verified=True,
            subscription_type="FREE",
        )
        await user.insert()
        return user

    loop = asyncio.new_event_loop()
    user = loop.run_until_complete(_setup())
    loop.close()
    yield user


# ── Playwright fixtures ───────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def browser_instance():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser_instance: Browser, live_server, test_user) -> Page:
    """Fresh browser context + logged-in page for each test."""
    context: BrowserContext = browser_instance.new_context(base_url=APP_BASE_URL)
    pg = context.new_page()

    # Log in
    pg.goto("/login")
    pg.fill('input[name="email"]', TEST_USER_EMAIL)
    pg.fill('input[name="password"]', TEST_USER_PASSWORD)
    pg.click('button[type="submit"]')
    pg.wait_for_url("**/app**", timeout=10_000)

    yield pg
    context.close()
