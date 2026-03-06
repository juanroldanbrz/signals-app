# Site Agents Design

**Date:** 2026-03-06
**Status:** Approved

## Problem

Generic Playwright crawling (`crawl_text` / `crawl`) gets blocked by sites like Skyscanner that require real interaction — search form submission, pagination, cookie flows. These sites need dedicated agents that know how to _use_ the site, not just read it.

## Goal

A registry of site-specific agents where each agent:
- Exposes typed tools (like an MCP server)
- Has an LLM orchestration loop that picks tools based on the signal query
- Works for both monitor signals (return a numeric value) and digest signals (return a summary)
- Maintains short-term in-session memory and long-term persisted memory per signal
- Uses BrightData WebSocket proxy + resource blocking for bot-protected premium domains

Skyscanner is the first agent. Adding a second agent means dropping a new folder and registering a domain.

## File Structure

```
src/crawling/
  site_agents/
    __init__.py          # registry: domain -> agent class + get_agent_for_url()
    base.py              # BaseSiteAgent protocol, AgentTool, AgentResult, ProgressCallback
    skyscanner/
      __init__.py
      types.py           # FlightResult, SearchParams, PriceCalendar (Pydantic)
      memory.py          # SkyMemory: in-session working state + persisted serialisation
      tools.py           # search_flights, get_cheapest, scan_date_range (Playwright actions)
      agent.py           # SkyAgent: LLM orchestration loop, tool dispatch

  browser.py             # get_page(): proxy-aware, resource-blocking page factory
  agent.py               # existing generic crawler (unchanged)
```

## Base Protocol (`base.py`)

Every site agent implements this protocol:

```python
class AgentTool(BaseModel):
    name: str
    description: str
    parameters: dict          # JSON schema for args

class AgentResult(BaseModel):
    value: float | None       # for monitor signals
    digest_content: str | None  # JSON for digest signals
    persisted_memory: dict    # updated state to save back to MongoDB

class SiteAgent(Protocol):
    domains: list[str]
    tools: list[AgentTool]

    async def run(
        self,
        query: str,
        signal_id: str,
        persisted_memory: dict,
        on_progress: ProgressCallback,
    ) -> AgentResult: ...
```

## Registry (`__init__.py`)

```python
SITE_AGENTS: dict[str, type[SiteAgent]] = {}

def register(agent_cls):
    for domain in agent_cls.domains:
        SITE_AGENTS[domain] = agent_cls
    return agent_cls

def get_agent_for_url(url: str) -> type[SiteAgent] | None:
    host = urlparse(url).hostname or ""
    return next((cls for domain, cls in SITE_AGENTS.items() if domain in host), None)
```

## Browser Factory (`browser.py`)

Reads two env vars:
- `BRIGHTDATA_WSS` — WebSocket endpoint for BrightData proxy
- `PREMIUM_DOMAINS` — comma-separated list of domains that require the proxy

When a URL's hostname matches a premium domain and `BRIGHTDATA_WSS` is set:
- Connect via `playwright.chromium.connect_over_cdp(BRIGHTDATA_WSS)`
- Install a route handler that aborts `image`, `font`, `media`, and `stylesheet` requests (bandwidth cost reduction)

Otherwise: standard `chromium.launch(headless=True)`.

The factory returns a `(browser, page)` tuple. Callers are responsible for closing the browser.

## Skyscanner Agent

### Types (`types.py`)

```python
class FlightResult(BaseModel):
    origin: str
    destination: str
    date: str               # YYYY-MM-DD
    return_date: str | None
    price: float
    currency: str
    airline: str | None
    duration_minutes: int | None
    url: str | None

class SearchParams(BaseModel):
    origin: str             # IATA code e.g. "LHR"
    destination: str        # IATA code e.g. "MAD"
    date_from: str          # YYYY-MM-DD
    date_to: str            # YYYY-MM-DD (inclusive)
    return_date: str | None = None
    passengers: int = 1

class PriceCalendar(BaseModel):
    params: SearchParams
    entries: list[FlightResult]   # one per departure date scanned

    def cheapest(self) -> FlightResult | None:
        return min(self.entries, key=lambda f: f.price, default=None)
```

### Memory (`memory.py`)

Two layers:

**In-session (`SkyMemory`):** lives only within one agent run.
```python
class SkyMemory:
    searches: list[SearchParams]
    results: list[FlightResult]
    cheapest_so_far: FlightResult | None
```

**Persisted:** serialised as JSON into `signal.agent_memory` in MongoDB.
```python
{
  "price_history": [{"route": "LHR-MAD", "date": "2026-04-01", "price": 89.0, "checked_at": "..."}],
  "last_search_params": {...}
}
```
`SkyMemory.to_persisted()` → dict to save back.
`SkyMemory.load_persisted(dict)` → restores history at run start.

### Tools (`tools.py`)

Three async functions, each accepting a Playwright `Page` and typed params:

| Tool | Input | Output |
|------|-------|--------|
| `search_flights(page, params)` | `SearchParams` | `list[FlightResult]` |
| `get_cheapest(results)` | `list[FlightResult]` | `FlightResult \| None` |
| `scan_date_range(page, params)` | `SearchParams` (date_from/to = range) | `PriceCalendar` |

`search_flights`: navigates to Skyscanner search URL, fills origin/dest/date fields, waits for results, parses flight cards.

`get_cheapest`: pure Python, no Playwright — sorts results by price.

`scan_date_range`: calls `search_flights` for each day in the range, accumulates into a `PriceCalendar`.

### Agent Orchestration Loop (`agent.py`)

```
1. Load persisted_memory -> initialise SkyMemory
2. Build tool descriptions list (name + description + JSON schema per tool)
3. Loop up to MAX_ITERATIONS (5):
   a. Serialise current session memory snapshot
   b. Prompt Gemini: query + memory snapshot + tool list
      -> returns ToolCall {tool: str, args: dict} | DoneCall {result: str, value: float | None}
   c. If DoneCall: build AgentResult, break
   d. Dispatch to tool function (open Playwright page, call tool, close page)
   e. Update SkyMemory with result, emit progress
4. Serialise updated persistent memory
5. Return AgentResult
```

Each tool call opens and closes its own Playwright page via `browser.py::get_page()`.

## Integration with Existing Executors

Single routing check added to `digest_executor.py` and `executor.py` before the existing crawl path:

```python
from src.crawling.site_agents import get_agent_for_url

agent_cls = get_agent_for_url(url)
if agent_cls:
    result = await agent_cls().run(query, str(signal.id), signal.agent_memory or {}, on_progress)
else:
    result = await crawl_text(url)   # unchanged
```

Signal model gets a new optional field: `agent_memory: dict = {}`.

## Config

Two new env vars added to `src/config.py`:

```
BRIGHTDATA_WSS=wss://brd-customer-hl_ddde05c6-zone-signalsapp:m2aa83mzysas@brd.superproxy.io:9222
PREMIUM_DOMAINS=skyscanner.com,skyscanner.net
```

## TDD Order

1. **`types.py`** — Pydantic models, `PriceCalendar.cheapest()` — pure unit tests, no browser
2. **`memory.py`** — `SkyMemory` load/update/serialise — pure unit tests
3. **`browser.py`** — resource blocking route handler logic — unit tests with mock route
4. **`tools.py`** — each tool with a mock Playwright `Page` — unit tests with `AsyncMock`
5. **`agent.py`** — orchestration loop with mock tools + mock Gemini — unit tests
6. **`__init__.py`** — registry lookup — unit tests
7. **Integration** — real BrightData + Skyscanner (`@pytest.mark.integration`)

## Non-Goals (this iteration)

- Multi-city or complex routing
- Fare class / cabin selection
- Storing full flight result history (only price history is persisted)
- A second site agent (structure ready, implementation deferred)
