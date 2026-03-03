# Signals App — Design Document
**Date:** 2026-03-01

## Overview

Signals is a personal alert and dashboard tool. Users write natural-language prompts describing what they want to monitor (e.g. "Alert me when the price of gold is > 30 USD"). The app uses an LLM to parse the prompt into a structured condition, then runs periodic checks and surfaces results on a live dashboard.

---

## Tech Stack

| Layer | Choice |
|---|---|
| Language | Python 3.14 |
| Package manager | uv |
| Web framework | FastAPI |
| Templates | Jinja2 |
| Database | MongoDB (Motor async driver + Beanie ODM) |
| LLM | Gemini Flash (google-generativeai SDK) |
| Search tool | DuckDuckGo search (duckduckgo-search library) |
| Scheduler | APScheduler (async) |
| CSS | Tailwind CSS (CDN) |
| Charts | Chart.js (CDN) |
| Partial updates | HTMX |
| UI aesthetic | Dark techy / data dashboard |

---

## Architecture

```
signals-app/
├── src/
│   ├── main.py                  # FastAPI app entrypoint, lifespan (scheduler start/stop)
│   ├── config.py                # Settings from .env (GEMINI_API_KEY, MONGO_URI)
│   ├── routes/
│   │   ├── landing.py           # GET / → landing page
│   │   ├── dashboard.py         # GET /app → signal list dashboard
│   │   └── signals.py           # CRUD + run-now + toggle alert
│   ├── services/
│   │   ├── llm.py               # Gemini Flash: parse prompt → ParsedSignal
│   │   ├── executor.py          # Run one signal check cycle
│   │   ├── search.py            # DuckDuckGo search wrapper
│   │   └── scheduler.py        # APScheduler: schedule/unschedule signals
│   ├── models/
│   │   ├── signal.py            # Signal Beanie document
│   │   └── signal_run.py        # SignalRun Beanie document
│   └── templates/
│       ├── base.html            # Dark layout, nav, HTMX + Tailwind + Chart.js
│       ├── landing.html         # Hero, features, CTA
│       ├── dashboard.html       # Signal grid cards
│       ├── signal_detail.html   # Chart + history + edit form
│       └── partials/
│           ├── signal_card.html # Single card (used by HTMX swaps)
│           └── create_modal.html
├── pyproject.toml
├── .env.example
└── .gitignore
```

---

## Data Flow

1. User submits a prompt via the create modal → `POST /signals`
2. `llm.py` calls Gemini Flash → returns structured `ParsedSignal` or `{"supported": false, "reason": "..."}`
3. If supported, signal is saved to MongoDB with `status: "active"`
4. APScheduler picks up the new signal and schedules a job at the signal's interval
5. On each tick: `executor.py` runs:
   a. DuckDuckGo search using `parsed.search_query`
   b. Gemini Flash extracts the numeric/boolean value from search results
   c. Condition is evaluated (`value > threshold`, etc.)
   d. `SignalRun` record saved to MongoDB
   e. `Signal.last_value`, `last_run_at`, `alert_triggered` updated
6. Dashboard re-renders via HTMX polling or page refresh

---

## Data Models

### Signal (MongoDB document)

```json
{
  "_id": "ObjectId",
  "name": "Gold price alert",
  "prompt": "Alert me when gold price > 30 USD",
  "parsed": {
    "topic": "gold price",
    "condition": ">",
    "threshold": 30,
    "unit": "USD",
    "search_query": "current gold price per gram USD"
  },
  "interval_minutes": 60,
  "alert_enabled": true,
  "status": "active",
  "created_at": "ISODate",
  "last_run_at": "ISODate",
  "last_value": 28.5,
  "alert_triggered": false,
  "consecutive_errors": 0
}
```

### SignalRun (MongoDB document)

```json
{
  "_id": "ObjectId",
  "signal_id": "ref → Signal",
  "ran_at": "ISODate",
  "value": 28.5,
  "alert_triggered": false,
  "status": "ok",
  "raw_result": "Gold is trading at $28.50..."
}
```

---

## Pages

### Landing (`/`)
- Dark hero: app name, tagline ("Monitor anything. Get alerted instantly.")
- Feature highlights: natural language, any topic, alert system
- CTA → "Go to App"

### Dashboard (`/app`)
- Grid of signal cards (responsive, 1–3 columns)
- Each card: name, prompt snippet, current value, alert badge, last-checked time
- Enable/disable alert toggle (HTMX)
- Edit button → signal detail
- "Run now" button (HTMX)
- Floating "+" button → create modal

### Signal Detail (`/app/signals/{id}`)
- Editable prompt (save re-parses via LLM)
- Configurable interval (dropdown)
- Enable/disable toggle
- Line chart (Chart.js): historical values over time
- Alert history table (latest 20 runs)

### Create Modal
- Textarea for natural language prompt
- Loading spinner while Gemini parses
- Error message if unsupported

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Unsupported prompt | Gemini returns `{supported: false, reason}` → shown to user, not saved |
| Executor failure | Run logged with `status: "error"`, signal card shows warning badge |
| 5 consecutive errors | Signal auto-paused, badge shows "needs attention" |
| MongoDB unavailable | FastAPI returns 503 with friendly error page |
| Gemini API error | Toast notification, signal not created |

---

## Configuration (.env)

```
GEMINI_API_KEY=...
MONGO_URI=mongodb://localhost:27017
MONGO_DB=signals
DEFAULT_INTERVAL_MINUTES=60
```

---

## Auth

None — single-user personal tool.

---

## Telegram

Not included in initial version. Toggle field `alert_enabled` is present in the model for future extension.
