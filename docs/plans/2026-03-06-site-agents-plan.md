# Site Agents Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a registry of site-specific Playwright agents — starting with Skyscanner — where each agent exposes typed tools, an LLM picks which tools to call per query, and results feed both monitor and digest signals.

**Architecture:** Each agent lives in `src/crawling/site_agents/<name>/` and implements the `SiteAgent` protocol. A registry maps hostnames to agent classes. Existing executors route to the agent when a URL matches; otherwise fall through to the existing generic crawl. A proxy-aware browser factory connects via BrightData WebSocket for premium domains and blocks images/fonts/media to save bandwidth.

**Tech Stack:** Python 3.14, Playwright async, Pydantic, Beanie/MongoDB, LiteLLM (Gemini), pytest + AsyncMock

---

### Task 1: Branch + Config

**Files:**
- Modify: `src/config.py`
- Modify: `.env` (local only, not committed)

**Step 1: Create feature branch**

```bash
git checkout -b feat/site-agents
```

**Step 2: Add env vars to config**

In `src/config.py`, add two fields inside `Settings`:

```python
brightdata_wss: str = ""          # wss://brd-customer-...@brd.superproxy.io:9222
premium_domains: str = "skyscanner.com,skyscanner.net"
```

**Step 3: Add to your local `.env`**

```
BRIGHTDATA_WSS=wss://brd-customer-hl_ddde05c6-zone-signalsapp:m2aa83mzysas@brd.superproxy.io:9222
PREMIUM_DOMAINS=skyscanner.com,skyscanner.net
```

**Step 4: Verify settings load**

```bash
uv run python -c "from src.config import settings; print(settings.premium_domains)"
```

Expected: `skyscanner.com,skyscanner.net`

**Step 5: Commit**

```bash
git add src/config.py
git commit -m "feat: add BRIGHTDATA_WSS and PREMIUM_DOMAINS config"
```

---

### Task 2: Skyscanner Types

**Files:**
- Create: `src/crawling/site_agents/__init__.py` (empty for now)
- Create: `src/crawling/site_agents/skyscanner/__init__.py` (empty)
- Create: `src/crawling/site_agents/skyscanner/types.py`
- Create: `tests/test_skyscanner_types.py`

**Step 1: Write the failing tests**

```python
# tests/test_skyscanner_types.py
import pytest
from src.crawling.site_agents.skyscanner.types import (
    FlightResult, SearchParams, PriceCalendar,
)


def test_flight_result_fields():
    f = FlightResult(
        origin="LHR", destination="MAD", date="2026-04-01",
        price=89.99, currency="EUR",
    )
    assert f.origin == "LHR"
    assert f.return_date is None
    assert f.airline is None


def test_search_params_defaults():
    p = SearchParams(origin="LHR", destination="MAD",
                     date_from="2026-04-01", date_to="2026-04-07")
    assert p.passengers == 1
    assert p.return_date is None


def test_price_calendar_cheapest():
    flights = [
        FlightResult(origin="LHR", destination="MAD", date="2026-04-01", price=120.0, currency="EUR"),
        FlightResult(origin="LHR", destination="MAD", date="2026-04-02", price=89.0, currency="EUR"),
        FlightResult(origin="LHR", destination="MAD", date="2026-04-03", price=105.0, currency="EUR"),
    ]
    params = SearchParams(origin="LHR", destination="MAD",
                          date_from="2026-04-01", date_to="2026-04-03")
    cal = PriceCalendar(params=params, entries=flights)
    assert cal.cheapest().price == 89.0
    assert cal.cheapest().date == "2026-04-02"


def test_price_calendar_cheapest_empty():
    params = SearchParams(origin="LHR", destination="MAD",
                          date_from="2026-04-01", date_to="2026-04-01")
    cal = PriceCalendar(params=params, entries=[])
    assert cal.cheapest() is None
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_skyscanner_types.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Create package directories**

```bash
mkdir -p src/crawling/site_agents/skyscanner
touch src/crawling/site_agents/__init__.py
touch src/crawling/site_agents/skyscanner/__init__.py
```

**Step 4: Write `types.py`**

```python
# src/crawling/site_agents/skyscanner/types.py
from pydantic import BaseModel


class FlightResult(BaseModel):
    origin: str
    destination: str
    date: str                    # YYYY-MM-DD departure date
    return_date: str | None = None
    price: float
    currency: str
    airline: str | None = None
    duration_minutes: int | None = None
    url: str | None = None


class SearchParams(BaseModel):
    origin: str                  # IATA code e.g. "LHR"
    destination: str             # IATA code e.g. "MAD"
    date_from: str               # YYYY-MM-DD
    date_to: str                 # YYYY-MM-DD inclusive
    return_date: str | None = None
    passengers: int = 1


class PriceCalendar(BaseModel):
    params: SearchParams
    entries: list[FlightResult]

    def cheapest(self) -> FlightResult | None:
        return min(self.entries, key=lambda f: f.price, default=None)
```

**Step 5: Run tests**

```bash
uv run pytest tests/test_skyscanner_types.py -v
```

Expected: 4 passed

**Step 6: Commit**

```bash
git add src/crawling/site_agents/ tests/test_skyscanner_types.py
git commit -m "feat: Skyscanner types — FlightResult, SearchParams, PriceCalendar"
```

---

### Task 3: Skyscanner Memory

**Files:**
- Create: `src/crawling/site_agents/skyscanner/memory.py`
- Create: `tests/test_skyscanner_memory.py`

**Step 1: Write failing tests**

```python
# tests/test_skyscanner_memory.py
import pytest
from src.crawling.site_agents.skyscanner.types import FlightResult, SearchParams
from src.crawling.site_agents.skyscanner.memory import SkyMemory


def _flight(price: float, date: str = "2026-04-01") -> FlightResult:
    return FlightResult(origin="LHR", destination="MAD", date=date,
                        price=price, currency="EUR")


def _params() -> SearchParams:
    return SearchParams(origin="LHR", destination="MAD",
                        date_from="2026-04-01", date_to="2026-04-07")


def test_memory_starts_empty():
    mem = SkyMemory()
    assert mem.searches == []
    assert mem.results == []
    assert mem.cheapest_so_far is None


def test_add_results_updates_cheapest():
    mem = SkyMemory()
    mem.add_results([_flight(120.0), _flight(89.0), _flight(105.0)])
    assert mem.cheapest_so_far.price == 89.0


def test_add_results_accumulates():
    mem = SkyMemory()
    mem.add_results([_flight(120.0)])
    mem.add_results([_flight(60.0)])
    assert len(mem.results) == 2
    assert mem.cheapest_so_far.price == 60.0


def test_to_persisted_serialises():
    mem = SkyMemory()
    mem.add_results([_flight(89.0, "2026-04-02")])
    mem.searches.append(_params())
    data = mem.to_persisted()
    assert "price_history" in data
    assert data["price_history"][0]["price"] == 89.0
    assert data["price_history"][0]["route"] == "LHR-MAD"
    assert "last_search_params" in data


def test_load_persisted_restores_history():
    stored = {
        "price_history": [{"route": "LHR-MAD", "date": "2026-04-02",
                            "price": 89.0, "checked_at": "2026-03-01T10:00:00"}],
        "last_search_params": {"origin": "LHR", "destination": "MAD",
                                "date_from": "2026-04-01", "date_to": "2026-04-07",
                                "passengers": 1},
    }
    mem = SkyMemory.from_persisted(stored)
    assert len(mem.price_history) == 1
    assert mem.price_history[0]["price"] == 89.0
    assert mem.last_search_params.origin == "LHR"


def test_session_snapshot_for_llm():
    mem = SkyMemory()
    mem.add_results([_flight(89.0, "2026-04-02")])
    snap = mem.session_snapshot()
    assert "89" in snap
    assert "LHR" in snap
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_skyscanner_memory.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Write `memory.py`**

```python
# src/crawling/site_agents/skyscanner/memory.py
from datetime import datetime, timezone
from src.crawling.site_agents.skyscanner.types import FlightResult, SearchParams


class SkyMemory:
    def __init__(self) -> None:
        self.searches: list[SearchParams] = []
        self.results: list[FlightResult] = []
        self.cheapest_so_far: FlightResult | None = None
        self.price_history: list[dict] = []
        self.last_search_params: SearchParams | None = None

    def add_results(self, flights: list[FlightResult]) -> None:
        self.results.extend(flights)
        for f in flights:
            if self.cheapest_so_far is None or f.price < self.cheapest_so_far.price:
                self.cheapest_so_far = f

    def to_persisted(self) -> dict:
        history = self.price_history.copy()
        now = datetime.now(timezone.utc).isoformat()
        for f in self.results:
            history.append({
                "route": f"{f.origin}-{f.destination}",
                "date": f.date,
                "price": f.price,
                "currency": f.currency,
                "checked_at": now,
            })
        return {
            "price_history": history,
            "last_search_params": (
                self.searches[-1].model_dump() if self.searches else None
            ),
        }

    @classmethod
    def from_persisted(cls, data: dict) -> "SkyMemory":
        mem = cls()
        mem.price_history = data.get("price_history", [])
        raw_params = data.get("last_search_params")
        if raw_params:
            mem.last_search_params = SearchParams(**raw_params)
        return mem

    def session_snapshot(self) -> str:
        lines = []
        if self.cheapest_so_far:
            f = self.cheapest_so_far
            lines.append(
                f"Cheapest so far: {f.origin}->{f.destination} on {f.date} "
                f"= {f.price} {f.currency}"
            )
        if self.results:
            lines.append(f"Flights found this session: {len(self.results)}")
        if self.price_history:
            lines.append(f"Historical entries: {len(self.price_history)}")
        return "\n".join(lines) if lines else "No data yet."
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_skyscanner_memory.py -v
```

Expected: 6 passed

**Step 5: Commit**

```bash
git add src/crawling/site_agents/skyscanner/memory.py tests/test_skyscanner_memory.py
git commit -m "feat: SkyMemory — in-session accumulation + persisted price history"
```

---

### Task 4: Site Agent Registry

**Files:**
- Modify: `src/crawling/site_agents/__init__.py`
- Create: `src/crawling/site_agents/base.py`
- Create: `tests/test_site_agent_registry.py`

**Step 1: Write failing tests**

```python
# tests/test_site_agent_registry.py
import pytest
from src.crawling.site_agents import get_agent_for_url, register, SITE_AGENTS
from src.crawling.site_agents.base import AgentTool, AgentResult


def test_get_agent_for_url_returns_none_for_unknown():
    assert get_agent_for_url("https://example.com/page") is None


def test_register_maps_domains():
    class FakeAgent:
        domains = ["fake-site.com"]
        tools = []
        async def run(self, *a, **kw): ...

    register(FakeAgent)
    assert get_agent_for_url("https://fake-site.com/search") is FakeAgent
    # cleanup
    for d in FakeAgent.domains:
        SITE_AGENTS.pop(d, None)


def test_get_agent_for_url_subdomain_match():
    class FakeAgent2:
        domains = ["testsite.net"]
        tools = []
        async def run(self, *a, **kw): ...

    register(FakeAgent2)
    assert get_agent_for_url("https://www.testsite.net/flights") is FakeAgent2
    for d in FakeAgent2.domains:
        SITE_AGENTS.pop(d, None)


def test_agent_tool_model():
    tool = AgentTool(
        name="search_flights",
        description="Search for flights on given route and date",
        parameters={"type": "object", "properties": {}},
    )
    assert tool.name == "search_flights"


def test_agent_result_model():
    result = AgentResult(value=89.0, digest_content=None, persisted_memory={})
    assert result.value == 89.0
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_site_agent_registry.py -v
```

Expected: `ImportError`

**Step 3: Write `base.py`**

```python
# src/crawling/site_agents/base.py
from collections.abc import Awaitable, Callable
from pydantic import BaseModel

type ProgressCallback = Callable[[str], Awaitable[None]] | None


class AgentTool(BaseModel):
    name: str
    description: str
    parameters: dict          # JSON schema for args


class AgentResult(BaseModel):
    value: float | None = None
    digest_content: str | None = None
    persisted_memory: dict = {}
```

**Step 4: Write `__init__.py`**

```python
# src/crawling/site_agents/__init__.py
from urllib.parse import urlparse

SITE_AGENTS: dict[str, type] = {}


def register(agent_cls: type) -> type:
    for domain in agent_cls.domains:
        SITE_AGENTS[domain] = agent_cls
    return agent_cls


def get_agent_for_url(url: str) -> type | None:
    host = urlparse(url).hostname or ""
    return next(
        (cls for domain, cls in SITE_AGENTS.items() if domain in host),
        None,
    )
```

**Step 5: Run tests**

```bash
uv run pytest tests/test_site_agent_registry.py -v
```

Expected: 5 passed

**Step 6: Commit**

```bash
git add src/crawling/site_agents/__init__.py src/crawling/site_agents/base.py \
        tests/test_site_agent_registry.py
git commit -m "feat: site agent registry — register(), get_agent_for_url(), base types"
```

---

### Task 5: Proxy-Aware Browser Factory

**Files:**
- Create: `src/crawling/browser.py`
- Create: `tests/test_browser_factory.py`

**Step 1: Write failing tests**

```python
# tests/test_browser_factory.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_get_page_blocks_heavy_resources_for_premium_domain():
    """Route handler must abort image/font/media/stylesheet requests."""
    from src.crawling.browser import _should_block

    assert _should_block("image") is True
    assert _should_block("font") is True
    assert _should_block("media") is True
    assert _should_block("stylesheet") is True
    assert _should_block("document") is False
    assert _should_block("script") is False
    assert _should_block("xhr") is False


@pytest.mark.asyncio
async def test_get_page_uses_proxy_for_premium_domain():
    """When BRIGHTDATA_WSS is set and domain is premium, use connect_over_cdp."""
    with patch("src.crawling.browser.settings") as mock_settings:
        mock_settings.brightdata_wss = "wss://fake-proxy"
        mock_settings.premium_domains = "skyscanner.com"

        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)

        mock_playwright = MagicMock()
        mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
        mock_playwright.chromium.launch = AsyncMock()

        from src.crawling.browser import get_page
        browser, page = await get_page("https://www.skyscanner.com/flights", mock_playwright)

        mock_playwright.chromium.connect_over_cdp.assert_called_once_with("wss://fake-proxy")
        mock_playwright.chromium.launch.assert_not_called()
        await browser.close()


@pytest.mark.asyncio
async def test_get_page_uses_direct_for_non_premium():
    """Non-premium domain must use standard chromium.launch."""
    with patch("src.crawling.browser.settings") as mock_settings:
        mock_settings.brightdata_wss = "wss://fake-proxy"
        mock_settings.premium_domains = "skyscanner.com"

        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)

        mock_playwright = MagicMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_playwright.chromium.connect_over_cdp = AsyncMock()

        from src.crawling.browser import get_page
        browser, page = await get_page("https://example.com/page", mock_playwright)

        mock_playwright.chromium.launch.assert_called_once()
        mock_playwright.chromium.connect_over_cdp.assert_not_called()
        await browser.close()


@pytest.mark.asyncio
async def test_get_page_uses_direct_when_no_wss():
    """Even for a premium domain, fall back to direct if BRIGHTDATA_WSS is empty."""
    with patch("src.crawling.browser.settings") as mock_settings:
        mock_settings.brightdata_wss = ""
        mock_settings.premium_domains = "skyscanner.com"

        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)

        mock_playwright = MagicMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_playwright.chromium.connect_over_cdp = AsyncMock()

        from src.crawling.browser import get_page
        browser, page = await get_page("https://www.skyscanner.com/flights", mock_playwright)

        mock_playwright.chromium.launch.assert_called_once()
        mock_playwright.chromium.connect_over_cdp.assert_not_called()
        await browser.close()
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_browser_factory.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Write `browser.py`**

```python
# src/crawling/browser.py
from urllib.parse import urlparse
from src.config import settings

_BLOCK_RESOURCE_TYPES = {"image", "font", "media", "stylesheet"}


def _should_block(resource_type: str) -> bool:
    return resource_type in _BLOCK_RESOURCE_TYPES


def _is_premium(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return any(d in host for d in settings.premium_domains.split(",") if d)


async def get_page(url: str, playwright) -> tuple:
    """
    Return (browser, page) for the given URL.
    - Premium domains with BRIGHTDATA_WSS set: connect via CDP proxy,
      block images/fonts/media/stylesheets.
    - All other URLs: standard headless Chromium.
    Caller is responsible for calling browser.close().
    """
    use_proxy = bool(settings.brightdata_wss) and _is_premium(url)

    if use_proxy:
        browser = await playwright.chromium.connect_over_cdp(settings.brightdata_wss)
        page = await browser.new_page()
        async def _block_route(route):
            if _should_block(route.request.resource_type):
                await route.abort()
            else:
                await route.continue_()
        await page.route("**/*", _block_route)
    else:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()

    return browser, page
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_browser_factory.py -v
```

Expected: 4 passed

**Step 5: Commit**

```bash
git add src/crawling/browser.py tests/test_browser_factory.py
git commit -m "feat: proxy-aware browser factory — BrightData CDP, resource blocking for premium domains"
```

---

### Task 6: Skyscanner Tools

**Files:**
- Create: `src/crawling/site_agents/skyscanner/tools.py`
- Create: `tests/test_skyscanner_tools.py`

**Step 1: Write failing tests**

```python
# tests/test_skyscanner_tools.py
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

    with patch("src.crawling.site_agents.skyscanner.tools.gemini_text",
               AsyncMock(return_value="[]")):
        result = await search_flights(mock_page, _make_params())

    assert isinstance(result, list)


@pytest.mark.asyncio
async def test_search_flights_parses_gemini_json():
    """search_flights must parse Gemini's JSON response into FlightResult objects."""
    from src.crawling.site_agents.skyscanner.tools import search_flights

    gemini_json = """[
        {"origin": "LHR", "destination": "MAD", "date": "2026-04-01",
         "price": 89.0, "currency": "EUR", "airline": "Iberia"}
    ]"""

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
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_skyscanner_tools.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Write `tools.py`**

```python
# src/crawling/site_agents/skyscanner/tools.py
import json
from datetime import date, timedelta
from src.crawling.site_agents.skyscanner.types import FlightResult, SearchParams, PriceCalendar
from src.services.tracing import gemini_text

_MAX_HTML_CHARS = 20_000


def _build_search_url(params: SearchParams) -> str:
    return (
        f"https://www.skyscanner.com/transport/flights"
        f"/{params.origin.lower()}/{params.destination.lower()}"
        f"/{params.date_from.replace('-', '')}/"
        f"?adults={params.passengers}&currency=EUR"
    )


async def search_flights(page, params: SearchParams) -> list[FlightResult]:
    """
    Navigate to Skyscanner search URL, extract page text, ask Gemini
    to parse flight results as JSON. Returns list[FlightResult].
    """
    url = _build_search_url(params)
    try:
        await page.goto(url, wait_until="load", timeout=30_000)
    except Exception:
        pass
    await page.wait_for_timeout(2_000)

    html = await page.content()
    text = html[:_MAX_HTML_CHARS]

    prompt = (
        f"Extract all flight offers from this Skyscanner page for "
        f"{params.origin} -> {params.destination} on {params.date_from}.\n"
        f"Return a JSON array of objects with keys: "
        f"origin, destination, date (YYYY-MM-DD), price (number), "
        f"currency (string), airline (string or null), duration_minutes (int or null).\n"
        f"If no flights found return [].\n\n"
        f"PAGE CONTENT:\n{text}"
    )

    raw = await gemini_text(name="skyscanner_parse_flights", prompt=prompt)
    try:
        data = json.loads(raw.strip())
        return [FlightResult(**item) for item in data]
    except Exception:
        return []


def get_cheapest(results: list[FlightResult]) -> FlightResult | None:
    """Return the flight with the lowest price, or None if list is empty."""
    return min(results, key=lambda f: f.price, default=None)


async def scan_date_range(page, params: SearchParams) -> PriceCalendar:
    """
    Call search_flights for each day between date_from and date_to (inclusive).
    Accumulates all results into a PriceCalendar.
    """
    start = date.fromisoformat(params.date_from)
    end = date.fromisoformat(params.date_to)
    all_flights: list[FlightResult] = []

    current = start
    while current <= end:
        day_params = params.model_copy(update={
            "date_from": current.isoformat(),
            "date_to": current.isoformat(),
        })
        flights = await search_flights(page, day_params)
        all_flights.extend(flights)
        current += timedelta(days=1)

    return PriceCalendar(params=params, entries=all_flights)
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_skyscanner_tools.py -v
```

Expected: 5 passed

**Step 5: Commit**

```bash
git add src/crawling/site_agents/skyscanner/tools.py tests/test_skyscanner_tools.py
git commit -m "feat: Skyscanner tools — search_flights, get_cheapest, scan_date_range"
```

---

### Task 7: Skyscanner Agent (Orchestration Loop)

**Files:**
- Create: `src/crawling/site_agents/skyscanner/agent.py`
- Modify: `src/crawling/site_agents/skyscanner/__init__.py`
- Create: `tests/test_skyscanner_agent.py`

**Step 1: Write failing tests**

```python
# tests/test_skyscanner_agent.py
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
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_skyscanner_agent.py -v
```

Expected: `ModuleNotFoundError`

**Step 3: Write `agent.py`**

```python
# src/crawling/site_agents/skyscanner/agent.py
import json
from playwright.async_api import async_playwright
from src.crawling.browser import get_page
from src.crawling.site_agents.base import AgentResult, AgentTool, ProgressCallback
from src.crawling.site_agents.skyscanner.memory import SkyMemory
from src.crawling.site_agents.skyscanner.tools import (
    get_cheapest, scan_date_range, search_flights,
)
from src.services.tracing import gemini_text

MAX_ITERATIONS = 5

_TOOLS: list[AgentTool] = [
    AgentTool(
        name="search_flights",
        description="Search Skyscanner for flights on a specific date. Returns a list of flights with prices.",
        parameters={
            "type": "object",
            "required": ["origin", "destination", "date_from", "date_to"],
            "properties": {
                "origin": {"type": "string", "description": "IATA airport code e.g. LHR"},
                "destination": {"type": "string", "description": "IATA airport code e.g. MAD"},
                "date_from": {"type": "string", "description": "Departure date YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "Same as date_from for single day"},
            },
        },
    ),
    AgentTool(
        name="scan_date_range",
        description="Search Skyscanner for flights across a range of dates. Use when user wants to find cheapest date in a window.",
        parameters={
            "type": "object",
            "required": ["origin", "destination", "date_from", "date_to"],
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "date_from": {"type": "string", "description": "Start of date range YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "End of date range YYYY-MM-DD"},
            },
        },
    ),
    AgentTool(
        name="done",
        description="Return the final answer when you have enough information.",
        parameters={
            "type": "object",
            "properties": {
                "value": {"type": "number", "description": "Numeric value for monitor signals (e.g. cheapest price)"},
                "summary": {"type": "string", "description": "Text summary for digest signals"},
            },
        },
    ),
]


def _tools_description() -> str:
    lines = []
    for t in _TOOLS:
        lines.append(f"- {t.name}: {t.description}")
    return "\n".join(lines)


class SkyAgent:
    domains = ["skyscanner.com", "skyscanner.net"]
    tools = _TOOLS

    async def run(
        self,
        query: str,
        signal_id: str,
        persisted_memory: dict,
        on_progress: ProgressCallback,
    ) -> AgentResult:
        async def emit(msg: str) -> None:
            if on_progress:
                await on_progress(msg)

        memory = SkyMemory.from_persisted(persisted_memory)
        final_value: float | None = None
        final_summary: str = ""

        for iteration in range(MAX_ITERATIONS):
            await emit(f"Agent iteration {iteration + 1}/{MAX_ITERATIONS}")

            prompt = (
                f"You are a Skyscanner flight search agent. Your task: {query}\n\n"
                f"Current session state:\n{memory.session_snapshot()}\n\n"
                f"Available tools:\n{_tools_description()}\n\n"
                f"Respond with ONLY a JSON object:\n"
                f'  {{"tool": "<tool_name>", "args": {{...}}}}\n'
                f"or to finish:\n"
                f'  {{"tool": "done", "value": <number or null>, "summary": "<text>"}}\n'
            )

            raw = await gemini_text(name="sky_agent_orchestrator", prompt=prompt)

            try:
                call = json.loads(raw.strip())
            except Exception:
                await emit(f"Could not parse LLM response: {raw[:80]}")
                break

            tool_name = call.get("tool")

            if tool_name == "done":
                final_value = call.get("value")
                final_summary = call.get("summary", "")
                await emit(f"Agent done — value={final_value}")
                break

            args = call.get("args", {})
            await emit(f"Calling tool: {tool_name}({args})")

            async with async_playwright() as pw:
                browser, page = await get_page("https://www.skyscanner.com", pw)
                try:
                    if tool_name == "search_flights":
                        from src.crawling.site_agents.skyscanner.types import SearchParams
                        params = SearchParams(**args)
                        flights = await search_flights(page, params)
                        memory.add_results(flights)
                        memory.searches.append(params)
                        await emit(f"Found {len(flights)} flights")

                    elif tool_name == "scan_date_range":
                        from src.crawling.site_agents.skyscanner.types import SearchParams
                        params = SearchParams(**args)
                        cal = await scan_date_range(page, params)
                        memory.add_results(cal.entries)
                        memory.searches.append(params)
                        await emit(f"Scanned {len(cal.entries)} flights across date range")

                    else:
                        await emit(f"Unknown tool: {tool_name}")
                finally:
                    await browser.close()

        return AgentResult(
            value=final_value,
            digest_content=final_summary or None,
            persisted_memory=memory.to_persisted(),
        )
```

**Step 4: Register the agent in `skyscanner/__init__.py`**

```python
# src/crawling/site_agents/skyscanner/__init__.py
from src.crawling.site_agents import register
from src.crawling.site_agents.skyscanner.agent import SkyAgent

register(SkyAgent)
```

**Step 5: Import the skyscanner package so it registers on app start**

In `src/crawling/site_agents/__init__.py`, add at the bottom:

```python
# Auto-register all site agents
import src.crawling.site_agents.skyscanner  # noqa: F401, E402
```

**Step 6: Run tests**

```bash
uv run pytest tests/test_skyscanner_agent.py -v
```

Expected: 3 passed

**Step 7: Commit**

```bash
git add src/crawling/site_agents/skyscanner/ tests/test_skyscanner_agent.py
git commit -m "feat: SkyAgent — LLM orchestration loop, tool dispatch, memory integration"
```

---

### Task 8: Signal Model — `agent_memory` Field

**Files:**
- Modify: `src/models/signal.py`

**Step 1: Add field**

In `src/models/signal.py`, add one line after `consecutive_errors`:

```python
agent_memory: dict = {}
```

**Step 2: Verify no existing tests break**

```bash
uv run pytest tests/ -v --ignore=tests/e2e -x
```

Expected: all pass

**Step 3: Commit**

```bash
git add src/models/signal.py
git commit -m "feat: Signal.agent_memory — persists site agent state between runs"
```

---

### Task 9: Executor Integration

**Files:**
- Modify: `src/services/digest_executor.py`
- Modify: `src/services/executor.py`
- Modify: `tests/test_digest_executor.py`

**Step 1: Write failing tests**

Add to `tests/test_digest_executor.py`:

```python
async def test_run_digest_routes_to_site_agent_for_premium_domain():
    """When source_url matches a registered site agent, use the agent not crawl_text."""
    from src.services.digest_executor import run_digest
    from src.crawling.site_agents.base import AgentResult

    signal = _make_signal(source_urls=["https://www.skyscanner.com/flights/lhr/mad/"])
    agent_result = AgentResult(
        value=None,
        digest_content="Flights from LHR to MAD from €89",
        persisted_memory={"price_history": []},
    )

    mock_agent_cls = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=agent_result)
    mock_agent_cls.return_value = mock_agent_instance

    with patch("src.services.digest_executor.get_agent_for_url",
               return_value=mock_agent_cls), \
         patch("src.services.digest_executor.crawl_text", AsyncMock()) as mock_crawl, \
         patch("src.services.digest_executor.gemini_text",
               AsyncMock(return_value='{"summary":"ok","key_points":[],"sources":[]}')):
        await run_digest(signal)

    # crawl_text must NOT have been called for the skyscanner URL
    mock_crawl.assert_not_called()
    mock_agent_instance.run.assert_called_once()
```

**Step 2: Run to verify failure**

```bash
uv run pytest tests/test_digest_executor.py::test_run_digest_routes_to_site_agent_for_premium_domain -v
```

Expected: FAIL (`crawl_text` gets called instead of the agent)

**Step 3: Update `digest_executor.py`**

At the top, add import:

```python
from src.crawling.site_agents import get_agent_for_url
```

Replace the URL crawl loop:

```python
    for url in signal.source_urls:
        await emit(f"Crawling {url} ...")
        agent_cls = get_agent_for_url(url)
        if agent_cls:
            await emit(f"Using site agent for {url} ...")
            agent_result = await agent_cls().run(
                query=signal.source_extraction_query or url,
                signal_id=str(signal.id),
                persisted_memory=signal.agent_memory or {},
                on_progress=on_progress,
            )
            signal.agent_memory = agent_result.persisted_memory
            if agent_result.digest_content:
                sources_text.append(agent_result.digest_content)
                source_refs.append(SourceRef(title=url, url=url))
            elif agent_result.value is not None:
                sources_text.append(f"Price found: {agent_result.value}")
                source_refs.append(SourceRef(title=url, url=url))
        else:
            result = await crawl_text(url)
            if result.get("blocked"):
                if subscription_type == "FREE":
                    raise PremiumRequired()
                else:
                    await emit(f"⚠ {url} — blocked by bot protection")
            elif result.get("text"):
                sources_text.append(
                    f"## {result['title'] or url}\nURL: {url}\n\n{result['text']}"
                )
                source_refs.append(SourceRef(
                    title=result["title"] or url,
                    url=url,
                    date=result["fetched_at"][:10],
                ))
                await emit(f"✓ {url} — {len(result['text']):,} chars")
            else:
                await emit(f"⚠ Could not fetch {url}")
```

**Step 4: Update `executor.py`** (monitor signals)

At the top of `executor.py`, add:

```python
from src.crawling.site_agents import get_agent_for_url
```

In the `run_signal` function, before the existing `crawl()` call:

```python
    agent_cls = get_agent_for_url(signal.source_url)
    if agent_cls:
        agent_result = await agent_cls().run(
            query=signal.source_extraction_query,
            signal_id=str(signal.id),
            persisted_memory=signal.agent_memory or {},
            on_progress=on_progress,
        )
        signal.agent_memory = agent_result.persisted_memory
        await signal.save()
        return agent_result.value, None, "", ""
```

**Step 5: Run all unit tests**

```bash
uv run pytest tests/ -v --ignore=tests/e2e -x
```

Expected: all pass

**Step 6: Commit**

```bash
git add src/services/digest_executor.py src/services/executor.py tests/test_digest_executor.py
git commit -m "feat: route premium domain URLs to site agents in digest and monitor executors"
```

---

### Task 10: Integration Test (Real Skyscanner via BrightData)

**Files:**
- Create: `tests/integration/test_skyscanner_agent_integration.py`

**Step 1: Write the integration test**

```python
# tests/integration/test_skyscanner_agent_integration.py
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
```

**Step 2: Run (skip if no BRIGHTDATA_WSS)**

```bash
uv run pytest tests/integration -m integration -s -v
```

Expected: skipped if `BRIGHTDATA_WSS` not set, or passes with real price data

**Step 3: Commit**

```bash
git add tests/integration/
git commit -m "test: Skyscanner integration test — real BrightData crawl with live price assertion"
```

---

### Task 11: Final Verification + Push

**Step 1: Run full unit test suite**

```bash
uv run pytest tests/ -v --ignore=tests/e2e --ignore=tests/integration -x
```

Expected: all pass

**Step 2: Push branch**

```bash
git push -u origin feat/site-agents
```

**Step 3: Open PR**

```bash
gh pr create \
  --title "feat: site agents — Skyscanner agent with MCP-style tools, BrightData proxy, persisted memory" \
  --body "$(cat <<'EOF'
## Summary
- Registry of site-specific Playwright agents (`src/crawling/site_agents/`)
- Skyscanner agent with 3 tools: `search_flights`, `get_cheapest`, `scan_date_range`
- LLM orchestration loop picks tools based on the signal query (works for monitor + digest)
- In-session memory accumulates flight results; persisted memory stores price history in MongoDB
- `browser.py` factory: BrightData CDP proxy for premium domains, blocks images/fonts/media/CSS
- Executor routing: URLs matching a registered agent skip `crawl_text` entirely
- `BRIGHTDATA_WSS` and `PREMIUM_DOMAINS` config via `.env`

## Test plan
- [ ] `uv run pytest tests/ --ignore=tests/e2e --ignore=tests/integration -v` — all unit tests pass
- [ ] `uv run pytest tests/integration -m integration -s -v` — live Skyscanner test with BRIGHTDATA_WSS set
- [ ] `uv run pytest tests/e2e -m e2e -k "not live" -s -v` — existing e2e suite unaffected
EOF
)"
```
