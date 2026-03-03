# Signals

> Monitor any value on any website — prices, stats, rankings — and get alerted when conditions are met.

```
╔═══════════════════════════════════════════════════════╗
║  SIGNALS  ▸  monitor anything on the web              ║
╠═══════════════════════════════════════════════════════╣
║  BTC / USD          $94,231.00   ▲  above $90k  🚨   ║
║  PS5 at Amazon      $449.99      ✓  below $500        ║
║  RTX 5090 stock     OUT OF STOCK ✓  any change        ║
╚═══════════════════════════════════════════════════════╝
```

Point Signals at any public URL and describe what to track in plain English. A browser agent navigates the page, a vision LLM reads the value, and you get a Telegram message (or an in-app alert) the moment your condition trips.

---

## How it works

```
You: "track the BTC price on CoinGecko"
        │
        ▼
  ┌─────────────┐     screenshot      ┌──────────────┐
  │  Playwright │ ──────────────────► │  Gemini LLM  │
  │  (headless) │                     │  (vision)    │
  └─────────────┘                     └──────┬───────┘
        ▲                                    │ extracted value
        │ every N hours                      ▼
  ┌─────────────┐              ┌─────────────────────────┐
  │  Scheduler  │              │  Condition evaluator    │
  │  (catch-up) │              │  above / below / equals │
  └─────────────┘              └──────────┬──────────────┘
                                          │ triggered?
                               ┌──────────▼──────────────┐
                               │  Telegram  +  In-app    │
                               │  alert                  │
                               └─────────────────────────┘
```

---

## Features

| Feature | Description |
|---------|-------------|
| **Natural language setup** | Describe what to track; the agent finds the URL and the right element |
| **Vision-powered extraction** | Gemini reads a page screenshot — works on SPAs, lazy-loaded content, any layout |
| **Flexible conditions** | Alert when a value goes `above`, `below`, `equals`, or on `any change` |
| **Restart-safe scheduler** | A single catch-up poller runs every 10 minutes; `next_run_at` is persisted in the DB so no runs are lost across restarts |
| **Telegram alerts** | Instant message when a condition triggers |
| **In-app alert feed** | `/app/alerts` — full history of every triggered run |
| **Config page** | `/app/config` — Telegram credentials, scheduler health, live event log |
| **LiteLLM gateway** | Swap the underlying LLM (GPT-4o, Claude, Gemini…) with one line |

---

## Stack

```
FastAPI  ▸  Jinja2  ▸  HTMX        server-rendered, zero JS framework
MongoDB  ▸  Beanie                  async ODM
LiteLLM  ▸  Gemini 3.0 Flash        vision + text LLM calls
Playwright  ▸  Chromium             headless browser for screenshots
APScheduler                         single catch-up poller
uv                                  dependency management
```

---

## Quickstart

### Prerequisites

- Python 3.14+
- MongoDB (local or remote)
- A [Gemini API key](https://aistudio.google.com/app/apikey)
- [`uv`](https://docs.astral.sh/uv/) — fast Python package manager

### Install

```bash
git clone https://github.com/bluggie/signals-app.git
cd signals-app

uv sync
uv run playwright install chromium
```

### Configure

```bash
cp .env.example .env   # then fill in your keys
```

```env
# Required
GEMINI_API_KEY=your_gemini_api_key

# Optional (defaults shown)
MONGO_URI=mongodb://localhost:27017
MONGO_DB=signals

# Optional — Langfuse observability
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=
LANGFUSE_HOST=https://cloud.langfuse.com
```

Telegram credentials are configured in-app at `/app/config` — no restart needed, stored in the DB.

### Run

```bash
uv run uvicorn src.main:app --reload
```

Open [http://localhost:8000/app](http://localhost:8000/app).

---

## Usage

### Create a signal

1. Click **+ NEW SIGNAL** on the dashboard
2. Describe what to track in the chat:
   - *"BTC price on CoinGecko"*
   - *"PS5 price on Amazon"*
   - *"RTX 5090 stock status on Best Buy"*
3. The agent discovers the URL and extraction query
4. Confirm — the signal is scheduled immediately

### Set an alert

On the signal detail page → **ALERTS** panel:

1. Enable alerts with the toggle
2. Choose a condition: `above`, `below`, `equals`, or `any change`
3. Set the threshold (not required for `any change`)
4. Click **SAVE CONDITION** — the next run evaluates it

Triggered alerts appear in the **Alerts** nav page and, if Telegram is configured, arrive as messages.

### Configure Telegram

Go to `/app/config`:

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token
2. Find your chat ID (send a message to the bot, then check `getUpdates`)
3. Paste both into the Telegram section and save

---

## Switching the LLM

LiteLLM supports 100+ providers. Change the `model` default in `src/services/tracing.py` and add the corresponding key to `.env`:

| Model | Key |
|-------|-----|
| `gemini/gemini-3.0-flash-preview` | `GEMINI_API_KEY` (default) |
| `openai/gpt-4o` | `OPENAI_API_KEY` |
| `anthropic/claude-sonnet-4-6` | `ANTHROPIC_API_KEY` |

---

## Running tests

```bash
# Unit tests (default)
uv run pytest tests/ -v

# Integration tests — live network required
uv run pytest tests/ -m integration -v
```

---

## Project structure

```
signals-app/
├── src/
│   ├── main.py                  FastAPI app + lifespan
│   ├── config.py                Settings from .env
│   ├── db.py                    Beanie init
│   ├── models/
│   │   ├── signal.py            Signal document (url, condition, schedule)
│   │   ├── signal_run.py        Per-run record
│   │   ├── app_config.py        Singleton config (Telegram creds)
│   │   └── app_event.py         Scheduler event log
│   ├── services/
│   │   ├── executor.py          Run a signal: Playwright → Gemini → result
│   │   ├── scheduler.py         Catch-up poller + condition evaluation
│   │   ├── notify.py            Telegram delivery
│   │   ├── tracing.py           LiteLLM wrappers + Langfuse logging
│   │   └── llm.py               Chat agent + signal spec parsing
│   ├── routes/
│   │   ├── signals.py           Signal CRUD + chat + run-now
│   │   ├── alerts.py            Alert feed
│   │   ├── config.py            App config page
│   │   └── dashboard.py         Main dashboard
│   └── templates/               Jinja2 + HTMX templates
├── tests/
├── pyproject.toml
└── README.md
```

---

## License

[MIT](LICENSE) © 2026 Juan Roldan
