# Digest Signals — Design Document
**Date:** 2026-03-05

## Overview

Add a second signal type — **Digest** — alongside the existing **Monitor** type. A Digest signal crawls a list of URLs (and optionally Brave Search results), summarises the content with an LLM, and stores a structured briefing with references, links, and dates. Refreshes on a schedule; always shows the latest summary with full history accessible on the detail page.

---

## 1. Data Model

### Signal (extend existing)

```python
signal_type: Literal["monitor", "digest"] = "monitor"
source_urls: list[str] = []       # digest: multiple crawl targets
search_query: str | None = None   # digest: Brave Search query (if enabled)
```

Existing `source_url` / `source_extraction_query` are monitor-only fields and remain unchanged.

### SignalRun (extend existing)

```python
digest_content: str | None = None  # JSON-serialised DigestContent; None for monitor runs
```

Monitor runs continue to use `value` + `raw_result`. Digest runs set `value = None` and store output in `digest_content`.

### DigestContent (Pydantic, in-memory only)

```python
class SourceRef(BaseModel):
    title: str
    url: str
    date: str | None   # extracted or page-metadata date; always shown to user

class DigestContent(BaseModel):
    summary: str               # 4–5 sentence paragraph
    key_points: list[str]      # 3–5 bullets
    sources: list[SourceRef]   # one entry per crawled URL / search result
```

### Migration

`scripts/migrate_signal_type.py` — one-shot script that sets `signal_type = "monitor"` on all existing Signal documents lacking the field. Safe to run multiple times (idempotent).

---

## 2. Creation Flow

### Type Picker (modal Step 0)

Before any form is shown, two cards appear side by side:

- **MONITOR** — *"Track a number. Get alerted when BTC drops below $50k, stock goes out, uptime falls."*
- **DIGEST** — *"Summarize content. Get a daily briefing on AI news, competitor updates, any topic."*

Clicking a card stores the type in a JS variable and shows the appropriate form.

### Monitor Form (unchanged)

Name → URL → extraction query → chart type → interval → **DRY RUN** → SSE console → flip to preview value → **SAVE**

### Digest Form

- **Name** — signal label
- **Topic / summarisation query** — e.g. "Latest news about AI safety"
- **URL list** — add/remove rows (at least one required)
- **Brave Search toggle** — when on: shows search query input; only active if user has Brave API key configured in settings
- **Interval** — same selector as monitor

Action: **PREVIEW** button → SSE console showing per-URL crawl progress → flip to back face showing:
- Summary paragraph
- Key points as bullets
- Source list with dates and links
- `⚠ Unverified` banner

Then **SAVE SIGNAL**.

---

## 3. Execution Service

### `src/services/digest_executor.py`

```
run_digest(signal) -> dict
  for each url in signal.source_urls:
    text = await crawl_text(url)           # Playwright + HTML→markdown
  if signal.search_query and brave configured:
    results = await brave_search(signal.search_query)
  assemble all text + metadata into LLM prompt
  response = await gemini_text(response_format=DigestContent)
  store as SignalRun(digest_content=response.model_dump_json())
```

### `src/crawling/agent.py` — `crawl_text(url)`

1. Playwright navigates to URL, waits for load
2. `page.content()` → raw HTML
3. BeautifulSoup strips `<script>`, `<style>`, `<nav>`, `<footer>`, `<header>`, `<aside>`, `<iframe>`, HTML comments
4. `html2text` converts remaining HTML → clean markdown
5. Truncate to ~8 000 tokens per source
6. Returns `{ text: str, title: str, url: str, fetched_at: datetime }`

### `src/services/brave.py`

Thin async `httpx` wrapper around `https://api.search.brave.com/res/v1/web/search`.
- Returns `list[SourceRef]` (title, url, description as date-stamped snippet)
- No-ops (returns `[]`) if `brave_api_key` not set in `AppConfig`

### Scheduler branching

```python
if signal.signal_type == "monitor":
    result = await run_signal(signal)
elif signal.signal_type == "digest":
    result = await run_digest(signal)
```

Digest signals do **not** evaluate alert conditions (no numeric value).

---

## 4. Dashboard & Detail Pages

### Dashboard card

Monitor card: unchanged (name, last value, status).

Digest card:
- Status dot + `DIGEST` badge
- First 2–3 sentences of latest summary (truncated with `…`)
- Source count + last updated timestamp
- No numeric value display

### Signal detail page

Branches on `signal_type`:

**Monitor** — unchanged: chart + run history table with values.

**Digest:**
- Latest digest panel: full summary, key points as bullets, source list (clickable links + dates)
- `⚠ Unverified` banner always shown
- Digest history below: list of past runs (timestamp + first sentence + expand)
- Alert condition section **hidden** — digests are informational only

---

## 5. Config & Settings

### AppConfig additions

```python
brave_api_key: str = ""
brave_search_enabled: bool = False
```

Stored per-user in `AppConfig` (not global `.env`).

### Config page

New **BRAVE SEARCH** card in the left column:
- Enable/disable toggle
- API key input
- Hint: *"Used by Digest signals to fetch web search results alongside your URLs"*

New route: `POST /app/config/brave`

---

## 6. Tests

### Gap-filling (existing code)

- `test_routes_signals.py` — `toggle-alert`, `update_signal`, `toggle-alert-page`
- `test_scheduler.py` — `evaluate_condition` all branches; alert channel gating

### New (digest feature)

- `test_digest_executor.py` — `run_digest()` mocked crawl + LLM; Brave absent; structured output
- `test_brave.py` — success, empty results, network error no-op
- `test_crawl_text.py` — HTML→markdown: strips script/style/nav; preserves content
- `test_routes_signals.py` additions — digest creation, digest preview SSE
- `test_models.py` additions — `signal_type` default, digest field defaults

---

## 7. New Dependencies

```
beautifulsoup4
html2text
```

No new runtime dependencies for Brave (uses existing `httpx`).

---

## 8. Migration

`scripts/migrate_signal_type.py`:
```python
# Idempotent — safe to run multiple times
await Signal.find({"signal_type": {"$exists": False}}).update_many(
    {"$set": {"signal_type": "monitor"}}
)
```
