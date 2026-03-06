import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.crawling.site_agents.skyscanner.types import SearchParams, FlightResult


def _make_params(**overrides) -> SearchParams:
    defaults = dict(origin="LHR", destination="MAD",
                    date_from="2026-04-01", date_to="2026-04-01")
    return SearchParams(**(defaults | overrides))


@pytest.mark.asyncio
async def test_search_flights_returns_list_of_flight_results():
    """search_flights must return a list[FlightResult] (may be empty on parse failure)."""
    from src.crawling.site_agents.skyscanner.tools import search_flights

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html></html>")
    mock_page.title = AsyncMock(return_value="Skyscanner")

    import json
    empty_json = json.dumps({"flights": []})
    with patch("src.crawling.site_agents.skyscanner.tools.gemini_text",
               AsyncMock(return_value=empty_json)):
        result = await search_flights(mock_page, _make_params())

    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_search_flights_parses_gemini_json():
    """search_flights must parse Gemini's JSON response into FlightResult objects."""
    from src.crawling.site_agents.skyscanner.tools import search_flights
    import json

    gemini_json = json.dumps({"flights": [
        {"origin": "LHR", "destination": "MAD", "date": "2026-04-01",
         "price": 89.0, "currency": "EUR", "airline": "Iberia"}
    ]})

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.wait_for_timeout = AsyncMock()
    mock_page.content = AsyncMock(return_value="<html>some content</html>")
    mock_page.title = AsyncMock(return_value="Skyscanner flights")

    with patch("src.crawling.site_agents.skyscanner.tools.gemini_text",
               AsyncMock(return_value=gemini_json)):
        result = await search_flights(mock_page, _make_params())

    assert len(result) == 1
    assert result[0].price == 89.0
    assert result[0].airline == "Iberia"
    assert isinstance(result[0], FlightResult)


@pytest.mark.asyncio
async def test_get_cheapest_picks_lowest_price():
    from src.crawling.site_agents.skyscanner.tools import get_cheapest

    flights = [
        FlightResult(origin="LHR", destination="MAD", date="2026-04-01", price=120.0, currency="EUR"),
        FlightResult(origin="LHR", destination="MAD", date="2026-04-02", price=75.0, currency="EUR"),
        FlightResult(origin="LHR", destination="MAD", date="2026-04-03", price=99.0, currency="EUR"),
    ]
    result = get_cheapest(flights)
    assert result.price == 75.0


@pytest.mark.asyncio
async def test_get_cheapest_returns_none_for_empty():
    from src.crawling.site_agents.skyscanner.tools import get_cheapest
    assert get_cheapest([]) is None


@pytest.mark.asyncio
async def test_scan_date_range_calls_search_per_day():
    """scan_date_range must call search_flights once for each day in the range."""
    from src.crawling.site_agents.skyscanner.tools import scan_date_range

    mock_page = AsyncMock()
    call_count = 0

    async def fake_search(page, params):
        nonlocal call_count
        call_count += 1
        return [FlightResult(origin=params.origin, destination=params.destination,
                             date=params.date_from, price=100.0 + call_count, currency="EUR")]

    with patch("src.crawling.site_agents.skyscanner.tools.search_flights", fake_search):
        params = _make_params(date_from="2026-04-01", date_to="2026-04-03")
        cal = await scan_date_range(mock_page, params)

    assert call_count == 3   # April 1, 2, 3
    assert len(cal.entries) == 3
    assert cal.cheapest() is not None


@pytest.mark.asyncio
async def test_scan_date_range_caps_at_7_days():
    """scan_date_range must never scan more than _MAX_SCAN_DAYS days."""
    from src.crawling.site_agents.skyscanner.tools import scan_date_range, _MAX_SCAN_DAYS

    mock_page = AsyncMock()
    call_count = 0

    async def fake_search(page, params):
        nonlocal call_count
        call_count += 1
        return []

    with patch("src.crawling.site_agents.skyscanner.tools.search_flights", fake_search):
        # 31-day range — should be capped at _MAX_SCAN_DAYS
        params = _make_params(date_from="2026-05-01", date_to="2026-05-31")
        cal = await scan_date_range(mock_page, params)

    assert call_count == _MAX_SCAN_DAYS
