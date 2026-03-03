# Alerts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add per-signal alert conditions, Telegram delivery, an in-app alert feed, a config page with event log and scheduler health.

**Architecture:** Condition evaluation happens inside `_run_signal_job` after value extraction. A new `notify.py` service handles Telegram delivery. Two new MongoDB collections (`AppConfig` singleton, `AppEvent` log) power the config page. All new pages are server-rendered Jinja2 + HTMX, matching the existing dark mono aesthetic.

**Tech Stack:** FastAPI, Beanie/MongoDB, Jinja2, HTMX, Tailwind CDN, httpx (already in env for Telegram calls)

---

### Task 1: Add condition fields to Signal model

**Files:**
- Modify: `src/models/signal.py`

**Step 1: Add fields after `consecutive_errors`**

```python
from typing import Literal   # already imported

# add after consecutive_errors:
condition_type: Literal["above", "below", "equals", "change"] | None = None
condition_threshold: float | None = None  # unused for "change"
```

**Step 2: Verify app still imports cleanly**

```bash
uv run python -c "from src.models.signal import Signal; print('ok')"
```
Expected: `ok`

**Step 3: Commit**

```bash
git add src/models/signal.py
git commit -m "feat: add condition_type and condition_threshold to Signal"
```

---

### Task 2: Create AppConfig model

**Files:**
- Create: `src/models/app_config.py`

**Step 1: Write the model**

```python
from beanie import Document


class AppConfig(Document):
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    class Settings:
        name = "app_config"

    @classmethod
    async def get_singleton(cls) -> "AppConfig":
        config = await cls.find_one()
        if not config:
            config = cls()
            await config.insert()
        return config
```

**Step 2: Verify import**

```bash
uv run python -c "from src.models.app_config import AppConfig; print('ok')"
```

**Step 3: Commit**

```bash
git add src/models/app_config.py
git commit -m "feat: add AppConfig singleton model"
```

---

### Task 3: Create AppEvent model

**Files:**
- Create: `src/models/app_event.py`

**Step 1: Write the model**

```python
from datetime import datetime, timezone
from typing import Literal
from beanie import Document, PydanticObjectId
from pydantic import Field


class AppEvent(Document):
    signal_id: PydanticObjectId
    signal_name: str
    value: float | None
    alert_triggered: bool
    status: Literal["ok", "error"]
    message: str = ""
    ran_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "app_events"
```

**Step 2: Verify import**

```bash
uv run python -c "from src.models.app_event import AppEvent; print('ok')"
```

**Step 3: Commit**

```bash
git add src/models/app_event.py
git commit -m "feat: add AppEvent log model"
```

---

### Task 4: Register new models in db.py

**Files:**
- Modify: `src/db.py`

**Step 1: Update imports and document_models list**

```python
from src.models.signal import Signal
from src.models.signal_run import SignalRun
from src.models.app_config import AppConfig
from src.models.app_event import AppEvent

# in init_beanie call:
document_models=[Signal, SignalRun, AppConfig, AppEvent],
```

**Step 2: Verify**

```bash
uv run python -c "from src.db import init_db; print('ok')"
```

**Step 3: Commit**

```bash
git add src/db.py
git commit -m "feat: register AppConfig and AppEvent with Beanie"
```

---

### Task 5: Create notify.py service

**Files:**
- Create: `src/services/notify.py`
- Test: `tests/test_notify.py`

**Step 1: Write the failing test**

```python
# tests/test_notify.py
import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_send_telegram_alert_sends_message():
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_client.post = AsyncMock()

        from src.services.notify import send_telegram_alert
        await send_telegram_alert(
            bot_token="testtoken",
            chat_id="123",
            signal_name="BTC Price",
            value=50000.0,
            condition="above 45000",
        )

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert "testtoken" in call_kwargs[0][0]
        assert "BTC Price" in call_kwargs[1]["json"]["text"]


@pytest.mark.asyncio
async def test_send_telegram_alert_noop_when_no_token():
    with patch("httpx.AsyncClient") as mock_client_cls:
        from src.services.notify import send_telegram_alert
        await send_telegram_alert(
            bot_token="",
            chat_id="123",
            signal_name="BTC Price",
            value=50000.0,
            condition="above 45000",
        )
        mock_client_cls.assert_not_called()
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_notify.py -v
```
Expected: ImportError or ModuleNotFoundError for `src.services.notify`

**Step 3: Implement notify.py**

```python
import httpx


async def send_telegram_alert(
    bot_token: str,
    chat_id: str,
    signal_name: str,
    value: float | None,
    condition: str,
) -> None:
    if not bot_token or not chat_id:
        return
    value_str = f"{value:.2f}" if value is not None else "—"
    text = f"🚨 ALERT: {signal_name}\nValue: {value_str}\nCondition: {condition}"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient() as client:
        await client.post(url, json={"chat_id": chat_id, "text": text})
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_notify.py -v
```
Expected: 2 passed

**Step 5: Commit**

```bash
git add src/services/notify.py tests/test_notify.py
git commit -m "feat: add telegram notify service with tests"
```

---

### Task 6: Add condition evaluation + notification + event logging to scheduler

**Files:**
- Modify: `src/services/scheduler.py`
- Test: `tests/test_condition_eval.py`

**Step 1: Write the failing tests for condition evaluation**

```python
# tests/test_condition_eval.py
import pytest
from src.services.scheduler import evaluate_condition


@pytest.mark.parametrize("condition_type,threshold,value,last_value,expected", [
    ("above", 100.0, 150.0, 100.0, True),
    ("above", 100.0, 50.0, 100.0, False),
    ("below", 100.0, 50.0, 100.0, True),
    ("below", 100.0, 150.0, 100.0, False),
    ("equals", 1.0, 1.0, 0.0, True),
    ("equals", 1.0, 0.0, 1.0, False),
    ("change", None, 200.0, 100.0, True),
    ("change", None, 100.0, 100.0, False),
    ("change", None, 100.0, None, False),   # no previous value: no alert
    (None, None, 100.0, None, False),        # no condition: never alert
])
def test_evaluate_condition(condition_type, threshold, value, last_value, expected):
    result = evaluate_condition(condition_type, threshold, value, last_value)
    assert result == expected
```

**Step 2: Run to verify it fails**

```bash
uv run pytest tests/test_condition_eval.py -v
```
Expected: ImportError for `evaluate_condition`

**Step 3: Add `evaluate_condition` to scheduler.py**

Add this function before `_run_signal_job`:

```python
def evaluate_condition(
    condition_type: str | None,
    threshold: float | None,
    value: float,
    last_value: float | None,
) -> bool:
    if condition_type == "above":
        return value > threshold
    if condition_type == "below":
        return value < threshold
    if condition_type == "equals":
        return value == threshold
    if condition_type == "change":
        return last_value is not None and value != last_value
    return False
```

**Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_condition_eval.py -v
```
Expected: 10 passed

**Step 5: Update `_run_signal_job` to use evaluate_condition, send notification, write AppEvent**

Replace the success block inside the `try` in `_run_signal_job`:

```python
async def _run_signal_job(signal_id: str):
    from src.models.signal import Signal, SignalStatus
    from src.models.signal_run import SignalRun
    from src.models.app_config import AppConfig
    from src.models.app_event import AppEvent
    from src.services.executor import run_signal
    from src.services.notify import send_telegram_alert

    signal = await Signal.get(signal_id)
    if not signal or signal.status == SignalStatus.PAUSED:
        return

    try:
        result = await run_signal(signal)
        value = result["value"]

        # Evaluate alert condition
        alert_triggered = False
        if value is not None and signal.alert_enabled:
            alert_triggered = evaluate_condition(
                signal.condition_type,
                signal.condition_threshold,
                value,
                signal.last_value,
            )

        run = SignalRun(
            signal_id=signal.id,
            value=value,
            alert_triggered=alert_triggered,
            raw_result=result["raw_result"],
            status=result["status"],
        )
        await run.insert()

        signal.last_run_at = datetime.now(timezone.utc)
        signal.last_value = value
        signal.alert_triggered = alert_triggered

        if result["status"] == "error":
            signal.consecutive_errors += 1
            if signal.consecutive_errors >= 5:
                signal.status = SignalStatus.PAUSED
        else:
            signal.consecutive_errors = 0
            signal.status = SignalStatus.ACTIVE

        # Send Telegram notification
        if alert_triggered:
            config = await AppConfig.get_singleton()
            condition_desc = _condition_description(signal)
            await send_telegram_alert(
                bot_token=config.telegram_bot_token,
                chat_id=config.telegram_chat_id,
                signal_name=signal.name,
                value=value,
                condition=condition_desc,
            )

        # Log event
        event_status = "error" if result["status"] == "error" else "ok"
        await AppEvent(
            signal_id=signal.id,
            signal_name=signal.name,
            value=value,
            alert_triggered=alert_triggered,
            status=event_status,
            message=result.get("raw_result", "")[:200],
        ).insert()

    except Exception as e:
        signal.consecutive_errors += 1
        signal.last_run_at = datetime.now(timezone.utc)
        if signal.consecutive_errors >= 5:
            signal.status = SignalStatus.PAUSED
        await AppEvent(
            signal_id=signal.id,
            signal_name=signal.name,
            value=None,
            alert_triggered=False,
            status="error",
            message=str(e)[:200],
        ).insert()

    await signal.save()
```

Also add this helper below `evaluate_condition`:

```python
def _condition_description(signal) -> str:
    ct = signal.condition_type
    t = signal.condition_threshold
    if ct == "above":
        return f"above {t}"
    if ct == "below":
        return f"below {t}"
    if ct == "equals":
        return f"equals {t}"
    if ct == "change":
        return "value changed"
    return ""
```

**Step 6: Run all tests**

```bash
uv run pytest tests/ -v
```
Expected: all pass

**Step 7: Commit**

```bash
git add src/services/scheduler.py tests/test_condition_eval.py
git commit -m "feat: condition evaluation + telegram alerts + event logging in scheduler"
```

---

### Task 7: Add alert-config route to signals.py

**Files:**
- Modify: `src/routes/signals.py`

**Step 1: Add the route at the end of the file**

```python
@router.post("/signals/{signal_id}/alert-config", response_class=HTMLResponse)
async def update_alert_config(
    request: Request,
    signal_id: PydanticObjectId,
    condition_type: Annotated[str, Form()] = "",
    condition_threshold: Annotated[str, Form()] = "",
):
    from src.templates_config import templates
    signal = await Signal.get(signal_id)
    if not signal:
        return HTMLResponse(status_code=404)

    signal.condition_type = condition_type if condition_type else None
    signal.condition_threshold = float(condition_threshold) if condition_threshold else None
    await signal.save()

    runs = await SignalRun.find(SignalRun.signal_id == signal.id).sort("-ran_at").limit(20).to_list()
    return templates.TemplateResponse(
        request, "signal_detail.html", {"signal": signal, "runs": runs}
    )
```

**Step 2: Verify app starts**

```bash
uv run python -c "from src.routes.signals import router; print('ok')"
```

**Step 3: Commit**

```bash
git add src/routes/signals.py
git commit -m "feat: add alert-config route for per-signal condition settings"
```

---

### Task 8: Update signal_detail.html ALERTS panel

**Files:**
- Modify: `src/templates/signal_detail.html`

**Step 1: Replace the existing ALERTS panel (lines 68–77) with:**

```html
<div class="p-5 rounded-lg border border-dark-border bg-dark-card">
  <h2 class="text-xs font-mono text-gray-500 tracking-wider mb-3">ALERTS</h2>

  <form method="POST" action="/signals/{{ signal.id }}/toggle-alert-page" class="mb-4">
    <button type="submit"
      class="w-full py-2 rounded text-xs font-mono border transition-all
             {% if signal.alert_enabled %}bg-neon-green/5 border-neon-green/20 text-neon-green hover:bg-neon-green/10{% else %}border-dark-border text-gray-600 hover:border-gray-500{% endif %}">
      {% if signal.alert_enabled %}ALERTS ENABLED — CLICK TO DISABLE{% else %}ALERTS DISABLED — CLICK TO ENABLE{% endif %}
    </button>
  </form>

  <form method="POST" action="/signals/{{ signal.id }}/alert-config">
    <label class="block text-xs text-gray-600 font-mono mb-1">CONDITION</label>
    <select name="condition_type" id="conditionType"
      onchange="document.getElementById('thresholdRow').style.display = (this.value === 'change' || this.value === '') ? 'none' : 'block'"
      class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50 mb-3">
      <option value="" {% if not signal.condition_type %}selected{% endif %}>— none —</option>
      <option value="above" {% if signal.condition_type == 'above' %}selected{% endif %}>above threshold</option>
      <option value="below" {% if signal.condition_type == 'below' %}selected{% endif %}>below threshold</option>
      <option value="equals" {% if signal.condition_type == 'equals' %}selected{% endif %}>equals value</option>
      <option value="change" {% if signal.condition_type == 'change' %}selected{% endif %}>any change</option>
    </select>

    <div id="thresholdRow" style="display: {% if signal.condition_type and signal.condition_type != 'change' %}block{% else %}none{% endif %}">
      {% if signal.chart_type == 'flag' %}
      <label class="block text-xs text-gray-600 font-mono mb-1">TARGET VALUE</label>
      <select name="condition_threshold"
        class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50 mb-3">
        <option value="1.0" {% if signal.condition_threshold == 1.0 %}selected{% endif %}>TRUE (1.0)</option>
        <option value="0.0" {% if signal.condition_threshold == 0.0 %}selected{% endif %}>FALSE (0.0)</option>
      </select>
      {% else %}
      <label class="block text-xs text-gray-600 font-mono mb-1">THRESHOLD</label>
      <input name="condition_threshold" type="number" step="any"
        value="{{ signal.condition_threshold if signal.condition_threshold is not none else '' }}"
        class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50 mb-3" />
      {% endif %}
    </div>

    <button type="submit"
      class="w-full py-2 bg-neon-green/10 border border-neon-green/30 text-neon-green text-xs font-mono rounded hover:bg-neon-green/20 transition-all">
      SAVE CONDITION
    </button>
  </form>
</div>
```

**Step 2: Verify template renders (start app and navigate to a signal detail page)**

**Step 3: Commit**

```bash
git add src/templates/signal_detail.html
git commit -m "feat: expand ALERTS panel with condition type and threshold UI"
```

---

### Task 9: Create config route + template

**Files:**
- Create: `src/routes/config.py`
- Create: `src/templates/config.html`

**Step 1: Write the route**

```python
# src/routes/config.py
from datetime import datetime, timezone
from typing import Annotated
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()


@router.get("/app/config", response_class=HTMLResponse)
async def config_page(request: Request):
    from src.templates_config import templates
    from src.models.app_config import AppConfig
    from src.models.app_event import AppEvent
    from src.models.signal import Signal, SignalStatus

    config = await AppConfig.get_singleton()
    events = await AppEvent.find_all().sort("-ran_at").limit(100).to_list()
    active_count = await Signal.find(Signal.status == SignalStatus.ACTIVE).count()
    paused_count = await Signal.find(Signal.status == SignalStatus.PAUSED).count()
    from src.services.scheduler import last_catch_up_at
    return templates.TemplateResponse(request, "config.html", {
        "config": config,
        "events": events,
        "active_count": active_count,
        "paused_count": paused_count,
        "last_catch_up_at": last_catch_up_at,
    })


@router.post("/app/config/telegram")
async def save_telegram_config(
    bot_token: Annotated[str, Form()] = "",
    chat_id: Annotated[str, Form()] = "",
):
    from src.models.app_config import AppConfig
    config = await AppConfig.get_singleton()
    config.telegram_bot_token = bot_token
    config.telegram_chat_id = chat_id
    await config.save()
    return RedirectResponse(url="/app/config", status_code=303)
```

**Step 2: Expose `last_catch_up_at` from scheduler.py**

Add at module level in `src/services/scheduler.py`:

```python
last_catch_up_at: datetime | None = None
```

And update `_catch_up_job` to set it:

```python
async def _catch_up_job():
    global last_catch_up_at
    last_catch_up_at = datetime.now(timezone.utc)
    # ... rest of function unchanged
```

**Step 3: Write config.html template**

```html
{% extends "base.html" %}
{% block title %}Config — Signals{% endblock %}
{% block content %}

<div class="flex items-center justify-between mb-8">
  <h1 class="text-2xl font-bold text-white tracking-wider">CONFIG</h1>
</div>

<div class="grid grid-cols-1 lg:grid-cols-3 gap-6">

  <!-- Left column -->
  <div class="space-y-4">

    <!-- Telegram -->
    <div class="p-5 rounded-lg border border-dark-border bg-dark-card">
      <h2 class="text-xs font-mono text-gray-500 tracking-wider mb-4">TELEGRAM ALERTS</h2>
      <form method="POST" action="/app/config/telegram">
        <label class="block text-xs text-gray-600 font-mono mb-1">BOT TOKEN</label>
        <input name="bot_token" type="password" value="{{ config.telegram_bot_token }}"
          placeholder="123456:ABC-DEF..."
          class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50 mb-3" />
        <label class="block text-xs text-gray-600 font-mono mb-1">CHAT ID</label>
        <input name="chat_id" value="{{ config.telegram_chat_id }}"
          placeholder="-100123456789"
          class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50 mb-4" />
        <button type="submit"
          class="w-full py-2 bg-neon-green/10 border border-neon-green/30 text-neon-green text-xs font-mono rounded hover:bg-neon-green/20 transition-all">
          SAVE
        </button>
      </form>
    </div>

    <!-- Scheduler health -->
    <div class="p-5 rounded-lg border border-dark-border bg-dark-card">
      <h2 class="text-xs font-mono text-gray-500 tracking-wider mb-4">SCHEDULER HEALTH</h2>
      <div class="space-y-2 text-xs font-mono">
        <div class="flex justify-between">
          <span class="text-gray-600">LAST RUN</span>
          <span class="text-gray-300">{{ last_catch_up_at | strftime('%H:%M:%S') if last_catch_up_at else '—' }}</span>
        </div>
        <div class="flex justify-between">
          <span class="text-gray-600">ACTIVE</span>
          <span class="text-neon-green">{{ active_count }}</span>
        </div>
        <div class="flex justify-between">
          <span class="text-gray-600">PAUSED</span>
          <span class="text-yellow-400">{{ paused_count }}</span>
        </div>
      </div>
    </div>

  </div>

  <!-- Right: Event log -->
  <div class="lg:col-span-2">
    <div class="p-5 rounded-lg border border-dark-border bg-dark-card">
      <h2 class="text-xs font-mono text-gray-500 tracking-wider mb-4">EVENT LOG</h2>
      {% if not events %}
      <p class="text-gray-700 font-mono text-sm text-center py-8">No events yet</p>
      {% else %}
      <div class="space-y-1 max-h-[600px] overflow-y-auto">
        {% for event in events %}
        <div class="flex items-center gap-3 p-2 rounded text-xs font-mono
          {% if event.status == 'error' %}border border-yellow-500/20 bg-yellow-500/5
          {% elif event.alert_triggered %}border border-red-500/20 bg-red-500/5
          {% else %}border border-dark-border bg-dark-bg/30{% endif %}">
          <span class="text-gray-700 w-32 flex-shrink-0">{{ event.ran_at | strftime('%m/%d %H:%M:%S') }}</span>
          <span class="text-gray-400 flex-1 truncate">{{ event.signal_name }}</span>
          <span class="{% if event.value is not none %}text-neon-blue{% else %}text-gray-600{% endif %} w-16 text-right">
            {{ "%.2f" | format(event.value) if event.value is not none else '—' }}
          </span>
          {% if event.alert_triggered %}
          <span class="text-red-400 w-12 text-right">ALERT</span>
          {% elif event.status == 'error' %}
          <span class="text-yellow-400 w-12 text-right">ERROR</span>
          {% else %}
          <span class="text-gray-700 w-12 text-right">OK</span>
          {% endif %}
        </div>
        {% endfor %}
      </div>
      {% endif %}
    </div>
  </div>

</div>

{% endblock %}
```

**Step 4: Commit**

```bash
git add src/routes/config.py src/templates/config.html src/services/scheduler.py
git commit -m "feat: config page with telegram settings, scheduler health, event log"
```

---

### Task 10: Create alerts feed route + template

**Files:**
- Create: `src/routes/alerts.py`
- Create: `src/templates/alerts.html`

**Step 1: Write the route**

```python
# src/routes/alerts.py
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter()


@router.get("/app/alerts", response_class=HTMLResponse)
async def alerts_feed(request: Request):
    from src.templates_config import templates
    from src.models.signal_run import SignalRun
    from src.models.signal import Signal

    alert_runs = await SignalRun.find(
        SignalRun.alert_triggered == True
    ).sort("-ran_at").limit(100).to_list()

    # Attach signal names
    signal_ids = {run.signal_id for run in alert_runs}
    signals = {s.id: s for s in await Signal.find({"_id": {"$in": list(signal_ids)}}).to_list()}

    return templates.TemplateResponse(request, "alerts.html", {
        "alert_runs": alert_runs,
        "signals": signals,
    })
```

**Step 2: Write alerts.html**

```html
{% extends "base.html" %}
{% block title %}Alerts — Signals{% endblock %}
{% block content %}

<div class="flex items-center justify-between mb-8">
  <div>
    <h1 class="text-2xl font-bold text-white tracking-wider">ALERTS</h1>
    <p class="text-gray-600 text-sm font-mono mt-1">{{ alert_runs | length }} triggered</p>
  </div>
</div>

{% if not alert_runs %}
<div class="text-center py-24 border border-dashed border-dark-border rounded-lg">
  <p class="text-gray-600 font-mono text-sm">No alerts triggered yet.</p>
</div>
{% else %}
<div class="rounded-lg border border-dark-border bg-dark-card overflow-hidden">
  <div class="divide-y divide-dark-border">
    {% for run in alert_runs %}
    {% set signal = signals.get(run.signal_id) %}
    <div class="flex items-center gap-4 px-5 py-3 hover:bg-dark-border/20 transition-colors">
      <div class="flex-shrink-0">
        <span class="text-xs px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20 font-mono">ALERT</span>
      </div>
      <div class="flex-1 min-w-0">
        {% if signal %}
        <a href="/app/signals/{{ signal.id }}" class="text-sm text-white font-mono hover:text-neon-blue transition-colors">
          {{ signal.name }}
        </a>
        {% else %}
        <span class="text-sm text-gray-500 font-mono">deleted signal</span>
        {% endif %}
        {% if run.value is not none %}
        <span class="text-neon-blue font-bold ml-3">{{ "%.2f" | format(run.value) }}</span>
        {% endif %}
      </div>
      <div class="text-gray-600 text-xs font-mono flex-shrink-0">
        {{ run.ran_at | strftime('%Y-%m-%d %H:%M') }}
      </div>
    </div>
    {% endfor %}
  </div>
</div>
{% endif %}

{% endblock %}
```

**Step 3: Commit**

```bash
git add src/routes/alerts.py src/templates/alerts.html
git commit -m "feat: alerts feed page"
```

---

### Task 11: Wire everything up — nav, main.py, db.py

**Files:**
- Modify: `src/templates/base.html`
- Modify: `src/main.py`

**Step 1: Update base.html nav — add Alerts and Config links**

Replace the nav links section in `base.html`:

```html
<div class="flex items-center gap-4">
  <a href="/app" class="text-sm text-gray-400 hover:text-neon-green transition-colors">Dashboard</a>
  <span class="text-dark-border">|</span>
  <a href="/app/alerts" class="text-sm text-gray-400 hover:text-neon-green transition-colors">Alerts</a>
  <span class="text-dark-border">|</span>
  <a href="/app/config" class="text-sm text-gray-400 hover:text-neon-green transition-colors">Config</a>
  <span class="text-dark-border">|</span>
  <span class="text-xs text-gray-600">v1.0</span>
</div>
```

**Step 2: Register routers in main.py**

```python
from src.routes import landing, dashboard
from src.routes import signals as signals_router
from src.routes import config as config_router
from src.routes import alerts as alerts_router

# in app setup:
app.include_router(config_router.router)
app.include_router(alerts_router.router)
```

**Step 3: Run all tests**

```bash
uv run pytest tests/ -v
```
Expected: all pass

**Step 4: Commit**

```bash
git add src/templates/base.html src/main.py
git commit -m "feat: wire up alerts + config pages — nav, routers"
```

---

## Verification Checklist

1. `uv run pytest tests/ -v` — all pass
2. Start the app: `uv run uvicorn src.main:app --reload`
3. Navigate to `/app/config` — Telegram form and scheduler health visible
4. Navigate to a signal detail → ALERTS panel shows condition dropdown
5. Navigate to `/app/alerts` — empty state or triggered runs
6. Set a condition, run-now, check `/app/alerts` and `/app/config` event log
