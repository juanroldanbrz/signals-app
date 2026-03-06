import pytest
from beanie import init_beanie
from bson import ObjectId
from httpx import AsyncClient, ASGITransport
from mongomock_motor import AsyncMongoMockClient
from unittest.mock import AsyncMock, patch

from src.main import app
from src.models.signal import Signal
from src.models.signal_run import SignalRun
from src.models.user import User
from src.services.auth import get_current_user
from src.crawling.site_agents.base import AgentResult


def _make_user() -> User:
    return User(
        id=ObjectId(),
        email="test@example.com",
        hashed_password="hashed",
        is_verified=True,
        subscription_type="UNLIMITED",
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
    with patch("src.main.init_db", AsyncMock()), patch("src.main.start_scheduler"):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c, user
    app.dependency_overrides.clear()


async def test_sky_preview_streams_value_for_flight_query(client):
    """sky-preview streams progress then a done event with value for a valid flight query."""
    c, _ = client

    mock_result = AgentResult(value=89.0, digest_content=None, persisted_memory={})

    with patch("src.crawling.site_agents.skyscanner.agent.SkyAgent.run",
               AsyncMock(return_value=mock_result)):
        resp = await c.post(
            "/signals/sky-preview",
            json={"query": "cheapest flight from SIN to SVQ between March 10-15 2026"},
        )

    assert resp.status_code == 200
    assert "89.0" in resp.text


async def test_sky_preview_streams_error_for_non_flight_query(client):
    """sky-preview returns an error event when the query is not about flights."""
    c, _ = client

    mock_result = AgentResult(
        value=None,
        digest_content="Not a flight query. Skyscanner agent only handles flight price searches.",
        persisted_memory={},
    )

    with patch("src.crawling.site_agents.skyscanner.agent.SkyAgent.run",
               AsyncMock(return_value=mock_result)):
        resp = await c.post(
            "/signals/sky-preview",
            json={"query": "what is the weather in London?"},
        )

    assert resp.status_code == 200
    assert "error" in resp.text
    assert "flight" in resp.text.lower()


async def test_sky_preview_error_when_no_value_and_no_content(client):
    """sky-preview returns a generic error when agent returns no value and no content."""
    c, _ = client

    mock_result = AgentResult(value=None, digest_content=None, persisted_memory={})

    with patch("src.crawling.site_agents.skyscanner.agent.SkyAgent.run",
               AsyncMock(return_value=mock_result)):
        resp = await c.post(
            "/signals/sky-preview",
            json={"query": "cheapest flight LHR to MAD"},
        )

    assert resp.status_code == 200
    assert "No flight price found" in resp.text


async def test_sky_preview_creates_skyscanner_monitor_signal(client):
    """POST /signals with source_url=skyscanner.com saves a monitor signal routed to SkyAgent."""
    c, user = client

    resp = await c.post(
        "/signals",
        data={
            "name": "SIN → SVQ Price",
            "signal_type": "monitor",
            "source_url": "https://www.skyscanner.com",
            "source_extraction_query": "cheapest flight from SIN to SVQ between 2026-03-10 and 2026-03-15",
            "chart_type": "line",
            "interval_minutes": "1440",
            "source_urls_json": "[]",
        },
    )

    assert resp.status_code in (200, 303)
    signal = await Signal.find_one(Signal.user_id == user.id)
    assert signal is not None
    assert signal.source_url == "https://www.skyscanner.com"
    assert "SIN" in signal.source_extraction_query
    assert "SVQ" in signal.source_extraction_query
    assert signal.signal_type == "monitor"
