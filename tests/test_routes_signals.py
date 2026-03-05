import pytest
from beanie import init_beanie
from bson import ObjectId
from httpx import AsyncClient, ASGITransport
from mongomock_motor import AsyncMongoMockClient
from unittest.mock import AsyncMock, patch

from src.main import app
from src.models.digest import DigestContent, SourceRef
from src.models.signal import Signal
from src.models.signal_run import SignalRun
from src.models.user import User
from src.services.auth import get_current_user


def _make_user() -> User:
    return User(
        id=ObjectId(),
        email="test@example.com",
        hashed_password="hashed",
        is_verified=True,
        subscription_type="FREE",
    )


@pytest.fixture(autouse=True)
async def beanie_init():
    client = AsyncMongoMockClient()
    await init_beanie(
        database=client.test_db,
        document_models=[Signal, SignalRun, User],
    )
    yield
    client.close()


@pytest.fixture()
async def client(beanie_init):
    user = _make_user()
    await user.insert()
    app.dependency_overrides[get_current_user] = lambda: user
    # Patch lifespan to skip real DB init and scheduler
    with patch("src.main.init_db", AsyncMock()), patch("src.main.start_scheduler"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c, user
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# alert_enabled default
# ---------------------------------------------------------------------------

async def test_signal_alert_disabled_by_default():
    signal = Signal(
        user_id=ObjectId(),
        name="Test",
        source_url="https://example.com",
        source_extraction_query="price",
    )
    assert signal.alert_enabled is False


# ---------------------------------------------------------------------------
# alert-config route — 200, saves condition, includes user in context
# ---------------------------------------------------------------------------

async def test_alert_config_saves_condition(client):
    c, user = client
    signal = Signal(
        user_id=user.id,
        name="BTC",
        source_url="https://example.com",
        source_extraction_query="BTC price",
    )
    await signal.insert()

    resp = await c.post(
        f"/signals/{signal.id}/alert-config",
        data={"condition_type": "above", "condition_threshold": "50000"},
    )

    assert resp.status_code == 200
    refreshed = await Signal.get(signal.id)
    assert refreshed.condition_type == "above"
    assert refreshed.condition_threshold == 50000.0


async def test_alert_config_clears_condition(client):
    c, user = client
    signal = Signal(
        user_id=user.id,
        name="BTC",
        source_url="https://example.com",
        source_extraction_query="BTC price",
        condition_type="above",
        condition_threshold=50000.0,
    )
    await signal.insert()

    resp = await c.post(
        f"/signals/{signal.id}/alert-config",
        data={"condition_type": "", "condition_threshold": ""},
    )

    assert resp.status_code == 200
    refreshed = await Signal.get(signal.id)
    assert refreshed.condition_type is None
    assert refreshed.condition_threshold is None


async def test_alert_config_returns_404_for_wrong_user(client):
    c, _ = client
    signal = Signal(
        user_id=ObjectId(),  # different user
        name="Other",
        source_url="https://example.com",
        source_extraction_query="price",
    )
    await signal.insert()

    resp = await c.post(
        f"/signals/{signal.id}/alert-config",
        data={"condition_type": "above", "condition_threshold": "100"},
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# digest-preview SSE endpoint
# ---------------------------------------------------------------------------

async def test_digest_preview_streams_progress_and_content(client):
    """Digest preview streams progress events then a done event with summary."""
    c, user = client

    mock_content = DigestContent(
        summary="AI is advancing rapidly.",
        key_points=["Point 1", "Point 2"],
        sources=[SourceRef(title="Example", url="https://example.com", date="2026-03-05")],
    )
    mock_result = {
        "status": "ok",
        "raw_result": "digest",
        "digest_content": mock_content.model_dump_json(),
        "content": mock_content,
    }

    with patch("src.services.digest_executor.run_digest", AsyncMock(return_value=mock_result)):
        resp = await c.post(
            "/signals/digest-preview",
            json={"source_urls": ["https://example.com"], "extraction_query": "AI news"},
        )

    assert resp.status_code == 200
    body = resp.text
    assert "AI is advancing rapidly." in body
    assert "Point 1" in body


async def test_digest_preview_returns_error_on_failure(client):
    """Digest preview returns a done event with error key when run_digest fails."""
    c, user = client

    with patch("src.services.digest_executor.run_digest", AsyncMock(return_value={
        "status": "error",
        "raw_result": "No content fetched",
        "digest_content": None,
        "content": None,
    })):
        resp = await c.post(
            "/signals/digest-preview",
            json={"source_urls": ["https://example.com"]},
        )

    assert resp.status_code == 200
    assert "No content fetched" in resp.text


# ---------------------------------------------------------------------------
# Signal creation — digest type
# ---------------------------------------------------------------------------

async def test_create_digest_signal(client):
    """POST /signals with signal_type=digest creates a digest signal with source_urls."""
    c, user = client

    resp = await c.post(
        "/signals",
        data={
            "name": "AI Digest",
            "signal_type": "digest",
            "source_url": "",
            "source_urls_json": '["https://example.com/ai", "https://example.com/ml"]',
            "source_extraction_query": "Latest AI research",
            "search_query": "AI research 2026",
            "chart_type": "line",
            "interval_minutes": "60",
        },
    )

    # Should redirect to /app (HTMX or plain)
    assert resp.status_code in (200, 303)

    signal = await Signal.find_one(Signal.user_id == user.id)
    assert signal is not None
    assert signal.signal_type == "digest"
    assert signal.source_urls == ["https://example.com/ai", "https://example.com/ml"]
    assert signal.search_query == "AI research 2026"
    assert signal.source_extraction_query == "Latest AI research"
