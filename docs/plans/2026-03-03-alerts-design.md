# Alerts Design — 2026-03-03

## Overview

Add Telegram and in-app alert delivery to signals, with per-signal condition evaluation, a config page for credentials and health, an event log, and an alert feed.

---

## 1. Signal Alert Conditions

### New fields on `Signal`

```python
condition_type: Literal["above", "below", "equals", "change"] | None = None
condition_threshold: float | None = None  # unused for "change"
```

### Evaluation logic (in `_run_signal_job`)

| condition_type | trigger when |
|---|---|
| `above` | `value > threshold` |
| `below` | `value < threshold` |
| `equals` | `value == threshold` |
| `change` | `value != last_value` (skip if `last_value` is None) |

- If `condition_type` is None: no alert evaluation (alert never fires)
- If `alert_enabled` is False: condition is evaluated but delivery is skipped
- `alert_triggered` on the signal reflects the most recent evaluation result

### UI (signal detail ALERTS panel)

- Condition type dropdown: `above / below / equals / change / none`
- Threshold input: numeric for above/below, TRUE/FALSE toggle for equals on flag signals, hidden for change/none
- Saved via a new `POST /signals/{id}/alert-config` endpoint

---

## 2. Config Page (`/app/config`)

### Telegram settings panel

- Fields: `telegram_bot_token`, `telegram_chat_id`
- Stored in a `AppConfig` MongoDB singleton document (not `.env`) — editable live without restart
- Saved via `POST /app/config/telegram`
- Delivery: `httpx.AsyncClient` POST to `https://api.telegram.org/bot{token}/sendMessage`
- Graceful no-op if credentials are absent

### Scheduler health panel

- Last catch-up run timestamp
- Count of active / paused signals
- Signals with consecutive errors > 0 (name + error count)

### Event log panel

- New `AppEvent` MongoDB collection
- Written by `_run_signal_job` on every run: signal name, value, alert_triggered, status, timestamp
- Config page shows last 100 events newest-first, color-coded: error=yellow, alert=red, ok=green
- No live polling — manual page refresh

---

## 3. Alert Feed (`/app/alerts`)

- Lists all `SignalRun` entries where `alert_triggered=True`, newest first
- Columns: signal name, value, condition description, timestamp
- Linked from the `ALERT` badge on signal cards

---

## 4. Nav Changes

Add two links to `base.html` nav: **Alerts** → `/app/alerts` and **Config** → `/app/config`

---

## 5. New Files

| File | Purpose |
|---|---|
| `src/models/app_config.py` | `AppConfig` singleton document (Telegram creds) |
| `src/models/app_event.py` | `AppEvent` log document |
| `src/routes/config.py` | `/app/config` GET + POST /telegram |
| `src/routes/alerts.py` | `/app/alerts` GET |
| `src/templates/config.html` | Config page template |
| `src/templates/alerts.html` | Alert feed template |
| `src/services/notify.py` | `send_telegram_alert(signal, value)` |

## 6. Modified Files

| File | Change |
|---|---|
| `src/models/signal.py` | Add `condition_type`, `condition_threshold` |
| `src/services/scheduler.py` | Evaluate condition, call notifier, write AppEvent |
| `src/routes/signals.py` | Add `POST /signals/{id}/alert-config` |
| `src/templates/signal_detail.html` | Expand ALERTS panel with condition UI |
| `src/templates/base.html` | Add Alerts + Config nav links |
| `src/main.py` | Register config + alerts routers |
| `src/db.py` | Register new Beanie models |
