import pytest
from beanie import init_beanie
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

from src.models.signal import Signal, SignalStatus
from src.models.signal_run import SignalRun, RunStatus


@pytest.fixture(autouse=True)
async def beanie_init():
    client = AsyncMongoMockClient()
    await init_beanie(database=client.test_db, document_models=[Signal, SignalRun])
    yield
    client.close()


async def test_signal_defaults():
    signal = Signal(
        user_id=ObjectId(),
        name="Gold Alert",
        source_url="https://example.com/gold",
        source_extraction_query="current gold price in USD",
    )
    assert signal.status == SignalStatus.ACTIVE
    assert signal.alert_enabled is False
    assert signal.interval_minutes == 60
    assert signal.chart_type == "line"
    assert signal.consecutive_errors == 0


async def test_signal_run_defaults():
    run = SignalRun(
        user_id=ObjectId(),
        signal_id=ObjectId(),
        value=28.5,
        alert_triggered=False,
        raw_result="Gold is at $28.50",
    )
    assert run.status == RunStatus.OK


async def test_signal_type_defaults_to_monitor():
    signal = Signal(
        user_id=ObjectId(),
        name="Test",
        source_url="https://example.com",
        source_extraction_query="price",
    )
    assert signal.signal_type == "monitor"
    assert signal.source_urls == []
    assert signal.search_query is None


async def test_digest_signal_fields():
    signal = Signal(
        user_id=ObjectId(),
        name="AI News",
        source_url="",
        source_extraction_query="latest AI news",
        signal_type="digest",
        source_urls=["https://techcrunch.com", "https://example.com"],
        search_query="AI safety 2026",
    )
    assert signal.signal_type == "digest"
    assert len(signal.source_urls) == 2
    assert signal.search_query == "AI safety 2026"


async def test_signal_run_digest_content_defaults_none():
    run = SignalRun(
        user_id=ObjectId(),
        signal_id=ObjectId(),
        value=None,
        alert_triggered=False,
        raw_result="ok",
    )
    assert run.digest_content is None
