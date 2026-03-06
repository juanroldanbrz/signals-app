import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_tool_call_json(tool: str, args: dict) -> str:
    import json
    return json.dumps({"tool": tool, "args": args})


def _make_done_json(value: float | None = None, summary: str = "") -> str:
    import json
    return json.dumps({"tool": "done", "value": value, "summary": summary})


@pytest.mark.asyncio
async def test_agent_run_returns_value_for_monitor_query():
    """Agent must call search_flights tool and return cheapest price as value."""
    from src.crawling.site_agents.skyscanner.agent import SkyAgent
    from src.crawling.site_agents.skyscanner.types import FlightResult

    cheap_flight = FlightResult(origin="LHR", destination="MAD",
                                date="2026-04-01", price=89.0, currency="EUR")

    # First Gemini call: LLM picks search_flights tool
    # Second Gemini call: LLM sees result, calls done
    gemini_responses = [
        _make_tool_call_json("search_flights", {
            "origin": "LHR", "destination": "MAD",
            "date_from": "2026-04-01", "date_to": "2026-04-01",
        }),
        _make_done_json(value=89.0),
    ]
    gemini_iter = iter(gemini_responses)

    with patch("src.crawling.site_agents.skyscanner.agent.gemini_text",
               AsyncMock(side_effect=lambda **kw: next(gemini_iter))), \
         patch("src.crawling.site_agents.skyscanner.agent.search_flights",
               AsyncMock(return_value=[cheap_flight])), \
         patch("src.crawling.site_agents.skyscanner.agent.async_playwright") as mock_pw:

        mock_pw.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_pw.return_value.__aexit__ = AsyncMock(return_value=False)

        with patch("src.crawling.site_agents.skyscanner.agent.get_page",
                   AsyncMock(return_value=(AsyncMock(), AsyncMock()))):
            agent = SkyAgent()
            result = await agent.run(
                query="cheapest flight LHR to MAD in April 2026",
                signal_id="abc123",
                persisted_memory={},
                on_progress=None,
            )

    assert result.value == 89.0
    assert result.persisted_memory.get("price_history") is not None


@pytest.mark.asyncio
async def test_agent_run_stops_after_max_iterations():
    """If LLM never calls done, agent must stop after MAX_ITERATIONS."""
    from src.crawling.site_agents.skyscanner.agent import SkyAgent, MAX_ITERATIONS

    # Always return a tool call (never done)
    with patch("src.crawling.site_agents.skyscanner.agent.gemini_text",
               AsyncMock(return_value=_make_tool_call_json("get_cheapest", {}))), \
         patch("src.crawling.site_agents.skyscanner.agent.search_flights",
               AsyncMock(return_value=[])), \
         patch("src.crawling.site_agents.skyscanner.agent.get_page",
               AsyncMock(return_value=(AsyncMock(), AsyncMock()))), \
         patch("src.crawling.site_agents.skyscanner.agent.async_playwright") as mock_pw:

        mock_pw.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_pw.return_value.__aexit__ = AsyncMock(return_value=False)

        agent = SkyAgent()
        result = await agent.run("cheapest flight", "abc", {}, None)

    # Should return a result (not raise) after hitting MAX_ITERATIONS
    assert result is not None


@pytest.mark.asyncio
async def test_agent_loads_and_saves_persisted_memory():
    """Persisted memory from previous runs must be loaded and updated after run."""
    from src.crawling.site_agents.skyscanner.agent import SkyAgent
    from src.crawling.site_agents.skyscanner.types import FlightResult

    prior_memory = {
        "price_history": [{"route": "LHR-MAD", "date": "2026-03-01",
                            "price": 95.0, "checked_at": "2026-03-01T00:00:00"}],
        "last_search_params": None,
    }
    flight = FlightResult(origin="LHR", destination="MAD",
                          date="2026-04-01", price=89.0, currency="EUR")

    gemini_responses = [
        _make_tool_call_json("search_flights", {
            "origin": "LHR", "destination": "MAD",
            "date_from": "2026-04-01", "date_to": "2026-04-01",
        }),
        _make_done_json(value=89.0),
    ]
    gemini_iter = iter(gemini_responses)

    with patch("src.crawling.site_agents.skyscanner.agent.gemini_text",
               AsyncMock(side_effect=lambda **kw: next(gemini_iter))), \
         patch("src.crawling.site_agents.skyscanner.agent.search_flights",
               AsyncMock(return_value=[flight])), \
         patch("src.crawling.site_agents.skyscanner.agent.get_page",
               AsyncMock(return_value=(AsyncMock(), AsyncMock()))), \
         patch("src.crawling.site_agents.skyscanner.agent.async_playwright") as mock_pw:

        mock_pw.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_pw.return_value.__aexit__ = AsyncMock(return_value=False)

        agent = SkyAgent()
        result = await agent.run("cheapest flight LHR MAD", "abc", prior_memory, None)

    # Both old and new history entries must be present
    history = result.persisted_memory["price_history"]
    assert len(history) >= 2
