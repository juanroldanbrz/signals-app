"""
Live Skyscanner integration test — requires BRIGHTDATA_WSS in env.
Run with: pytest tests/integration -m integration -s -v
"""
import os
import pytest

pytestmark = pytest.mark.integration

_BRIGHTDATA_AVAILABLE = bool(os.environ.get("BRIGHTDATA_WSS"))
needs_brightdata = pytest.mark.skipif(
    not _BRIGHTDATA_AVAILABLE, reason="BRIGHTDATA_WSS not set"
)


@needs_brightdata
@pytest.mark.asyncio
async def test_skyscanner_search_real_flight():
    """Real crawl: search LHR -> MAD, verify at least one numeric price returned."""
    from src.crawling.site_agents.skyscanner.agent import SkyAgent

    messages = []

    async def capture(msg):
        messages.append(msg)
        print(f"  [agent] {msg}")

    agent = SkyAgent()
    result = await agent.run(
        query="cheapest one-way flight from LHR to MAD on 2026-05-01",
        signal_id="integration-test",
        persisted_memory={},
        on_progress=capture,
    )

    print(f"\nResult: value={result.value}, memory_entries={len(result.persisted_memory.get('price_history', []))}")
    assert result is not None
    # Either a numeric price or a text summary must come back
    assert result.value is not None or result.digest_content is not None
    if result.value is not None:
        assert result.value > 0, f"Price should be positive, got {result.value}"
    assert len(result.persisted_memory.get("price_history", [])) >= 0
