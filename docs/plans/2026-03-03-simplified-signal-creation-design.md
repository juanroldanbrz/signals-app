# Simplified Signal Creation — Design

**Date:** 2026-03-03

## Context

The existing signal creation flow is a three-phase chat+discovery modal backed by a Brave Search agent, SSE streaming, LLM-driven URL discovery, and a complex `ParsedSignal` sub-document. This is being replaced with a direct, minimal form-based flow.

## Goals

- User provides URL + extraction query + chart type; the app verifies it works before saving.
- Remove all agentic complexity (Brave search, LLM chat, SSE streaming, derived signals).
- Keep Gemini for the actual value extraction (vision for numeric, text for flag).
- Alerts are deferred — configured after signal creation, not during.

---

## Data Model

`Signal` document (MongoDB via Beanie):

| Field | Type | Notes |
|---|---|---|
| `name` | `str` | User-provided |
| `source_url` | `str` | Required |
| `source_extraction_query` | `str` | Required |
| `chart_type` | `"line" \| "bar" \| "flag"` | Default: `"line"` |
| `interval_minutes` | `int` | Default: 60 |
| `alert_enabled` | `bool` | Default: `True` |
| `status` | `"active" \| "paused" \| "error"` | |
| `last_value` | `float \| None` | `1.0`/`0.0` for flag |
| `last_run_at` | `datetime \| None` | |
| `alert_triggered` | `bool` | |
| `consecutive_errors` | `int` | |

**Removed fields:** `ParsedSignal`, `conversation_history`, `derived`, `source_selector`, `source_verified`, `prompt`, `description`, `metric_description`, `dashboard_chart_type`.

**Flag signals** store `1.0` (true) or `0.0` (false) as `last_value` so `SignalRun` storage is unchanged. The card renders flag values as ✓ / ✗.

---

## Backend

### Files deleted
- `src/services/discovery.py` — Brave search, SSE emit, agentic URL discovery
- `src/services/llm.py` — chat agent, `run_chat_turn`, `parse_prompt`, `SignalSpec`

### Files simplified
- `src/services/executor.py` — remove `_derived_search_and_extract`; keep `_screenshot_and_extract` (Playwright → Gemini vision) and `run_signal`
- `src/routes/signals.py` — remove `/signals/chat`, `/signals/discover/stream`, `/screenshots/{filename}`; add `POST /signals/preview`

### New endpoint

```
POST /signals/preview
Content-Type: application/json

{ "url": "...", "extraction_query": "...", "chart_type": "line" }

→ 200 { "value": 67432.10, "screenshot_url": "/screenshots/abc.png" }
→ 200 { "error": "Could not extract value. Raw: ..." }
```

Internals:
1. Playwright opens URL (headless Chromium), full-page screenshot
2. Save screenshot to `/tmp/signals_screenshots/`
3. `chart_type == "flag"`: Gemini text prompt → "return only true or false"
   `chart_type` line/bar: Gemini vision prompt → "return only the number"
4. Returns value or error message

### pyproject.toml
No removals — `httpx` is kept for Langfuse tracing.

---

## Frontend

### Modal structure (create_modal.html)

Existing modal backdrop/shell is unchanged. Contents replaced with a single CSS 3D flip card.

**Front face — form:**
- Name (text input)
- URL (text input)
- What to extract (text input)
- Chart type (radio: Line / Bar / Flag)
- Interval (select: 1h / 2h / 6h / 12h / 24h)
- **Dry Run** button

**Back face — preview:**
- Extracted value (number, or ✓ TRUE / ✗ FALSE for flag)
- Source domain + screenshot link
- **← Try Again** (flips back, fields preserved)
- **Save Signal** (submits POST /signals, closes modal)

### Signal card updates
- Replace `signal.prompt[:80]` with domain of `source_url`
- Render `last_value` as ✓/✗ when `chart_type == "flag"`
- Remove `signal.parsed.unit` reference

---

## What is NOT in scope
- Alert configuration (deferred to signal detail page)
- Chart rendering changes
- User accounts / multi-tenancy
