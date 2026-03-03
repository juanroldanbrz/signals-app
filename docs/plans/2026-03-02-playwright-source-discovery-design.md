# Playwright Source Discovery — Design

**Date:** 2026-03-02
**Status:** Approved

---

## Problem

The current data fetching approach (DuckDuckGo text search → Gemini extracts number from snippet text) is fragile and imprecise. Search snippets are truncated, context-poor, and change with every run. There is no stable reference to where the data actually lives.

---

## Solution

Replace runtime DuckDuckGo search with a one-time **source discovery** step that runs during signal creation. A Playwright browser navigates to the real page, identifies the best DOM element for the metric, and stores a reusable extraction config. Every scheduled run goes directly to the stored URL and screenshots the element (or full page), sending the image to Gemini vision to extract the value.

---

## Data Model

Four new fields added to `Signal`:

```python
source_url: str | None = None              # canonical URL, e.g. coinmarketcap.com/currencies/bitcoin/
source_selector: str | None = None         # CSS selector for element screenshot; None = full page
source_extraction_query: str | None = None # Gemini vision prompt, e.g. "What is the Bitcoin price in USD?"
source_verified: bool = False              # True once discovery succeeds at creation time
```

### Runtime execution path (updated `executor.py`)

Always: Playwright navigates to `source_url` → screenshots `source_selector` element (if set) or full page → sends screenshot + `source_extraction_query` to Gemini vision → parses float → evaluates condition.

Fallback for legacy signals without `source_url`: existing DuckDuckGo + text extraction path (unchanged).

---

## Discovery Service

**File:** `src/services/discovery.py`

**Entry point:** `discover_source(topic, search_query, url_hint=None) -> DiscoveryResult`

```python
class DiscoveryResult(BaseModel):
    success: bool
    url: str | None = None
    selector: str | None = None        # None = full page screenshot
    extraction_query: str | None = None
    value: float | None = None
    error: str | None = None
```

**Flow:**

1. **Find URL** — if `url_hint` provided, use it directly. Otherwise DuckDuckGo search for `search_query`, take first result URL.
2. **Navigate** — Playwright (async) navigates to URL, waits for network idle.
3. **Find selector** — send truncated page HTML to Gemini, ask it to return the single CSS selector most likely containing the metric value. If Gemini returns a valid selector, verify it exists in the DOM.
4. **Screenshot** — screenshot the selector element (if found) or the full page.
5. **Extract value** — send screenshot + extraction query to Gemini vision. Parse returned number.
6. **Return** `DiscoveryResult` with url, selector (or None), extraction_query, and value.

If `url_hint` is provided (user rejected initial result and suggested a site), skip step 1 and go straight to step 2.

---

## New Endpoint

```
POST /signals/discover
  body:    { topic: str, search_query: str, url_hint?: str }
  returns: DiscoveryResult
```

Called by the modal after the agent conversation completes. Can be called multiple times (on user rejection with a new `url_hint`).

---

## Modal Flow (Phase 1.5)

A new intermediate phase between the chat phase and the confirmation card:

```
[AGENT] > Requirements clear. Scanning data source...

         ⟳ SCANNING SOURCE...

[AGENT] > Found: coinmarketcap.com/currencies/bitcoin/
          Current value: 67,432.10 USD

          Is this the right source?
          [A] Yes — confirm   [B] No — suggest a different site
```

- **[A] Yes** → transition to confirmation card with SOURCE + VALUE rows added
- **[B] No** → agent asks "Which website should I check?" → user provides URL → re-POST to `/signals/discover` with `url_hint` → loops

### Updated confirmation card

```
┌─ SIGNAL SPEC ──────────────────────────────────────────────┐
│ NAME       Bitcoin Price Alert                             │
│ METRIC     Bitcoin price in USD, sourced via web          │
│ ALERT      triggers when price > 60000 USD                │
│ DASHBOARD  Line chart — price over time                   │
│ INTERVAL   Every 1h                                       │
│ SOURCE     coinmarketcap.com/currencies/bitcoin/          │
│ VALUE      67,432.10 USD            ← live, from discovery│
└────────────────────────────────────────────────────────────┘
[ CONFIRM & CREATE ]   [ ← REVISE ]
```

---

## What Changes

| File | Change |
|------|--------|
| `src/models/signal.py` | Add 4 new fields |
| `src/services/discovery.py` | New file — full discovery flow |
| `src/services/executor.py` | Screenshot-based execution path using stored config |
| `src/routes/signals.py` | New `POST /signals/discover` endpoint; extend `POST /signals` |
| `src/templates/partials/create_modal.html` | Phase 1.5 discovery UI + updated spec card |

## What Does NOT Change

- Chat conversation flow (Phase 1) — unchanged
- Signal detail page — unchanged
- Scheduler — unchanged
- All other routes — unchanged

---

## Success Criteria

- [ ] Vague signal (e.g. "monitor Tesla stock") discovers a real URL and extracts a live value before confirmation
- [ ] User can reject the found source and provide a URL hint, discovery retries
- [ ] Stored `source_url` + `source_selector` + `source_extraction_query` are used on every scheduled run
- [ ] Legacy signals (no `source_url`) still work via DuckDuckGo fallback
- [ ] Discovery failure (can't extract value) surfaces a clear error in the modal
