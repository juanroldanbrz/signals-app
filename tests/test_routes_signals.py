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
