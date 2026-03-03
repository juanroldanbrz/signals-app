![Signals](img/landing.png)

# Signals

Monitor any value on any website — prices, stats, rankings — and get alerted when conditions are met.

Write a prompt in plain English. Signals watches it for you and sends a Telegram message the moment your condition trips.

![Signal detail](img/btc.png)

---

## How it works

1. **Describe** what you want to track ("BTC price on CoinGecko", "PS5 price on Amazon")
2. The agent finds the right URL and figures out how to extract the value
3. Playwright opens the page and takes a screenshot on a schedule
4. Gemini reads the screenshot and extracts the number
5. If the condition is met → Telegram alert + in-app notification

---

## Stack

| Layer | Technology |
|-------|-----------|
| Web framework | FastAPI + Jinja2 + HTMX (server-rendered, no JS framework) |
| Database | MongoDB via Beanie (async ODM) |
| LLM | LiteLLM → Gemini 3.0 Flash (vision + text) |
| Browser | Playwright headless Chromium |
| Scheduler | APScheduler — single catch-up poller every 10 min |
| Package manager | `uv` |

### Architecture

```
Browser (HTMX)
    │
    ▼
FastAPI routes
    │
    ├── /signals/chat     ← LLM chat agent (signal creation)
    ├── /signals/run      ← manual trigger
    ├── /app/alerts       ← triggered alert history
    └── /app/config       ← Telegram credentials + event log
    │
    ├── services/executor.py    ← Playwright screenshot → Gemini vision → value
    ├── services/scheduler.py   ← catch-up poller + condition evaluation
    ├── services/notify.py      ← Telegram delivery
    └── services/tracing.py     ← LiteLLM wrappers + Langfuse observability
    │
MongoDB (Beanie ODM)
    ├── Signal            ← url, query, schedule, condition, next_run_at
    ├── SignalRun         ← per-run record (value, status, timestamp)
    ├── AppConfig         ← Telegram credentials (singleton)
    └── AppEvent          ← scheduler event log
```

---

## Local setup

### Prerequisites

- Python 3.14+
- MongoDB running locally (or set `MONGO_URI`)
- A [Gemini API key](https://aistudio.google.com/app/apikey)
- [`uv`](https://docs.astral.sh/uv/)

### Install

```bash
git clone https://github.com/juanroldanbrz/signals-app.git
cd signals-app

uv sync
uv run playwright install chromium
```

### Configure

```bash
cp .env.example .env
```

Open `.env` and fill in your values:

```env
GEMINI_API_KEY=your_gemini_api_key

# Optional
MONGO_URI=mongodb://localhost:27017
MONGO_DB=signals

# Optional — URL discovery via Brave Search
BRAVE_SEARCH_API_KEY=your_brave_key

# Optional — LLM observability via Langfuse
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
```

Telegram credentials are configured inside the app at `/app/config` — no restart needed.

### Run

```bash
uv run uvicorn src.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000).

---

## Deploy with Docker

```bash
docker compose up -d
```

The `docker-compose.yml` starts both the app and MongoDB. Make sure your `.env` file is present — it is mounted automatically.

To run just the app against an existing MongoDB:

```bash
docker build -t signals-app .
docker run -p 8000:8000 --env-file .env signals-app
```

---

## Alerts

On any signal's detail page → **ALERTS** panel:

1. Enable alerts with the toggle
2. Choose a condition: `above`, `below`, `equals`, or `any change`
3. Set the threshold (not needed for `any change`)
4. Save — the next scheduled run evaluates the condition

When triggered, alerts appear in `/app/alerts` and (if configured) are sent via Telegram.

---

## Switching the LLM

LiteLLM supports 100+ providers. Change the `model` default in `src/services/tracing.py` and add the matching API key to `.env`:

```python
# src/services/tracing.py
async def gemini_vision(..., model: str = "openai/gpt-4o") -> str:
```

```env
OPENAI_API_KEY=sk-...
```

---

## Tests

```bash
# Unit tests
uv run pytest tests/ -v

# Integration tests (live network)
uv run pytest tests/ -m integration -v
```

---

## License

[MIT](LICENSE) © 2026 Juan Roldan
