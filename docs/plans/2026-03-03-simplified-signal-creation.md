# Simplified Signal Creation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the complex chat+discovery signal creation flow with a simple form + Gemini dry-run flip card, removing all agentic/search complexity.

**Architecture:** A modal flip card — form on the front, preview result on the back. A new `POST /signals/preview` endpoint runs Playwright + Gemini and returns the extracted value. On success, user flips to the back and saves.

**Tech Stack:** FastAPI, Beanie/MongoDB, Playwright, Google Gemini (vision), HTMX, Tailwind CSS, vanilla JS

---

### Task 1: Delete dead service files and stale tests

**Files:**
- Delete: `src/services/discovery.py`
- Delete: `src/services/llm.py`
- Delete: `tests/test_search.py` (imports `src.services.search` — stale)
- Delete: `tests/test_llm.py` (tests llm service being deleted)
- Delete: `tests/test_routes_signals.py` (tests `parse_prompt` being deleted)

**Step 1: Delete the files**

```bash
rm src/services/discovery.py src/services/llm.py
rm tests/test_search.py tests/test_llm.py tests/test_routes_signals.py
```

**Step 2: Run remaining tests to see baseline**

```bash
uv run pytest tests/ -v
```
Expected: Some failures due to stale imports — that's fine, we fix them in subsequent tasks.

**Step 3: Commit**

```bash
git add -A
git commit -m "chore: delete discovery, llm services and stale tests"
```

---

### Task 2: Simplify the Signal model

**Files:**
- Modify: `src/models/signal.py`
- Modify: `tests/test_models.py`

**Step 1: Rewrite `src/models/signal.py`**

```python
from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from beanie import Document
from pydantic import Field


class SignalStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class Signal(Document):
    name: str
    source_url: str
    source_extraction_query: str
    chart_type: Literal["line", "bar", "flag"] = "line"
    interval_minutes: int = 60
    alert_enabled: bool = True
    status: SignalStatus = SignalStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_run_at: datetime | None = None
    last_value: float | None = None
    alert_triggered: bool = False
    consecutive_errors: int = 0

    class Settings:
        name = "signals"
```

**Step 2: Rewrite `tests/test_models.py`**

```python
import pytest
from beanie import init_beanie
from bson import ObjectId
from mongomock_motor import AsyncMongoMockClient

from src.models.signal import Signal, SignalStatus
from src.models.signal_run import SignalRun, RunStatus


@pytest.fixture(autouse=True)
async def beanie_init():
    client = AsyncMongoMockClient()
    await init_beanie(database=client.test_db, document_models=[Signal, SignalRun])
    yield
    client.close()


async def test_signal_defaults():
    signal = Signal(
        name="Gold Alert",
        source_url="https://example.com/gold",
        source_extraction_query="current gold price in USD",
    )
    assert signal.status == SignalStatus.ACTIVE
    assert signal.alert_enabled is True
    assert signal.interval_minutes == 60
    assert signal.chart_type == "line"
    assert signal.consecutive_errors == 0


async def test_signal_run_defaults():
    run = SignalRun(
        signal_id=ObjectId(),
        value=28.5,
        alert_triggered=False,
        raw_result="Gold is at $28.50",
    )
    assert run.status == RunStatus.OK
```

**Step 3: Run tests**

```bash
uv run pytest tests/test_models.py -v
```
Expected: PASS

**Step 4: Commit**

```bash
git add src/models/signal.py tests/test_models.py
git commit -m "refactor: simplify Signal model — remove ParsedSignal, derived, conversation_history"
```

---

### Task 3: Simplify executor.py

**Files:**
- Modify: `src/services/executor.py`
- Modify: `tests/test_executor.py`

**Step 1: Rewrite `src/services/executor.py`**

Remove `evaluate_condition`, `_derived_search_and_extract`, `selector` handling (no CSS selectors in new model).
Add `_screenshot_and_flag` for flag signals.

```python
import re
from playwright.async_api import async_playwright
from src.services.tracing import gemini_vision


async def _screenshot_and_extract(url: str, extraction_query: str) -> tuple[float | None, str]:
    """Navigate to url, full-page screenshot, extract numeric value via Gemini vision."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="load", timeout=30000)
            screenshot = await page.screenshot(type="png", full_page=True)
            await browser.close()
    except Exception as e:
        return None, f"Browser error: {str(e)[:200]}"

    raw = await gemini_vision(
        name="executor_extract",
        image=screenshot,
        prompt=(
            f"{extraction_query}\n"
            f"Return ONLY the number (e.g. 67432.10), no units, no text.\n"
            f"If you cannot find a clear numeric value, return null."
        ),
    )
    raw = raw.strip()
    if raw.lower() in ("null", "none", ""):
        return None, f"Gemini could not extract value. Raw: {raw}"
    raw_stripped = raw.replace(",", "")
    match = re.search(r"\d+\.?\d*", raw_stripped)
    if match:
        try:
            return float(match.group()), raw
        except ValueError:
            pass
    return None, f"Could not parse number from: {raw}"


async def _screenshot_and_flag(url: str, extraction_query: str) -> tuple[float | None, str]:
    """Navigate to url, full-page screenshot, extract true/false via Gemini. Returns 1.0 or 0.0."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="load", timeout=30000)
            screenshot = await page.screenshot(type="png", full_page=True)
            await browser.close()
    except Exception as e:
        return None, f"Browser error: {str(e)[:200]}"

    raw = await gemini_vision(
        name="executor_flag",
        image=screenshot,
        prompt=f"{extraction_query}\nReturn ONLY: true or false. Nothing else.",
    )
    raw = raw.strip().lower()
    if "true" in raw:
        return 1.0, raw
    if "false" in raw:
        return 0.0, raw
    return None, f"Could not parse true/false from: {raw}"


async def run_signal(signal) -> dict:
    """Run one check cycle for a signal."""
    if signal.chart_type == "flag":
        value, raw_result = await _screenshot_and_flag(
            url=signal.source_url,
            extraction_query=signal.source_extraction_query,
        )
    else:
        value, raw_result = await _screenshot_and_extract(
            url=signal.source_url,
            extraction_query=signal.source_extraction_query,
        )

    if value is None:
        return {"value": None, "alert_triggered": False, "raw_result": raw_result, "status": "error"}

    return {"value": value, "alert_triggered": False, "raw_result": raw_result, "status": "ok"}
```

**Step 2: Rewrite `tests/test_executor.py`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.executor import _screenshot_and_extract, _screenshot_and_flag


def _mock_pw(screenshot_bytes):
    """Helper: returns a context manager mock for async_playwright."""
    mock_page = AsyncMock()
    mock_page.goto = AsyncMock()
    mock_page.screenshot = AsyncMock(return_value=screenshot_bytes)
    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_browser.close = AsyncMock()
    mock_p = MagicMock()
    mock_p.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_p)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    return mock_ctx


@pytest.mark.asyncio
async def test_screenshot_and_extract_returns_float():
    with patch("src.services.executor.async_playwright", return_value=_mock_pw(b"fake_png")):
        with patch("src.services.executor.gemini_vision", AsyncMock(return_value="67432.10")):
            value, _ = await _screenshot_and_extract("https://example.com", "BTC price in USD")
    assert value == 67432.10


@pytest.mark.asyncio
async def test_screenshot_and_extract_returns_none_on_null():
    with patch("src.services.executor.async_playwright", return_value=_mock_pw(b"fake_png")):
        with patch("src.services.executor.gemini_vision", AsyncMock(return_value="null")):
            value, msg = await _screenshot_and_extract("https://example.com", "BTC price")
    assert value is None
    assert "could not extract" in msg.lower()


@pytest.mark.asyncio
async def test_screenshot_and_flag_true():
    with patch("src.services.executor.async_playwright", return_value=_mock_pw(b"fake_png")):
        with patch("src.services.executor.gemini_vision", AsyncMock(return_value="true")):
            value, _ = await _screenshot_and_flag("https://example.com", "Is the site online?")
    assert value == 1.0


@pytest.mark.asyncio
async def test_screenshot_and_flag_false():
    with patch("src.services.executor.async_playwright", return_value=_mock_pw(b"fake_png")):
        with patch("src.services.executor.gemini_vision", AsyncMock(return_value="false")):
            value, _ = await _screenshot_and_flag("https://example.com", "Is price above 100k?")
    assert value == 0.0
```

**Step 3: Run tests**

```bash
uv run pytest tests/test_executor.py -v
```
Expected: 4 tests PASS

**Step 4: Commit**

```bash
git add src/services/executor.py tests/test_executor.py
git commit -m "refactor: simplify executor — remove derived path, add flag support"
```

---

### Task 4: Rewrite routes/signals.py

**Files:**
- Modify: `src/routes/signals.py`

**Step 1: Rewrite the file**

Key changes from the current version:
- Remove `ChatRequest`, `POST /signals/chat`, `GET /signals/discover/stream`
- Move `SCREENSHOTS_DIR` + `_save_screenshot` inline (since discovery.py is deleted)
- Keep `GET /screenshots/{filename}` route (still needed for preview screenshot links)
- Add `POST /signals/preview`
- Simplify `POST /signals` create (new model fields, no ParsedSignal)
- Simplify `POST /signals/{id}/update` (no parse_prompt)
- Keep: delete, toggle-alert, toggle-alert-page, run-now, get card

```python
import re
import uuid
from pathlib import Path
from typing import Annotated
from beanie import PydanticObjectId
from fastapi import APIRouter, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel as PydanticBaseModel
from src.models.signal import Signal, SignalStatus
from src.models.signal_run import SignalRun
from src.services.scheduler import schedule_signal, unschedule_signal

router = APIRouter()

SCREENSHOTS_DIR = Path("/tmp/signals_screenshots")
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def _save_screenshot(data: bytes) -> str:
    filename = f"{uuid.uuid4().hex}.png"
    (SCREENSHOTS_DIR / filename).write_bytes(data)
    return f"/screenshots/{filename}"


@router.get("/screenshots/{filename}")
async def serve_screenshot(filename: str):
    path = SCREENSHOTS_DIR / filename
    if not path.exists() or path.suffix != ".png":
        raise HTTPException(status_code=404)
    return Response(content=path.read_bytes(), media_type="image/png")


class PreviewRequest(PydanticBaseModel):
    url: str
    extraction_query: str
    chart_type: str = "line"


@router.post("/signals/preview")
async def preview_signal(body: PreviewRequest):
    from fastapi.responses import JSONResponse
    from playwright.async_api import async_playwright
    from src.services.tracing import gemini_vision

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(body.url, wait_until="load", timeout=30000)
            screenshot = await page.screenshot(type="png", full_page=True)
            await browser.close()
    except Exception as e:
        return JSONResponse({"error": f"Could not load page: {str(e)[:200]}"})

    screenshot_url = _save_screenshot(screenshot)

    if body.chart_type == "flag":
        raw = await gemini_vision(
            name="preview_flag",
            image=screenshot,
            prompt=f"{body.extraction_query}\nReturn ONLY: true or false. Nothing else.",
        )
        raw = raw.strip().lower()
        if "true" in raw:
            return JSONResponse({"value": 1.0, "flag": True, "screenshot_url": screenshot_url})
        if "false" in raw:
            return JSONResponse({"value": 0.0, "flag": False, "screenshot_url": screenshot_url})
        return JSONResponse({"error": f"Could not determine true/false. Got: {raw[:80]}", "screenshot_url": screenshot_url})

    raw = await gemini_vision(
        name="preview_extract",
        image=screenshot,
        prompt=(
            f"{body.extraction_query}\n"
            f"Return ONLY the number (e.g. 67432.10), no units, no text.\n"
            f"If you cannot find a clear numeric value, return null."
        ),
    )
    raw = raw.strip()
    if raw.lower() in ("null", "none", ""):
        return JSONResponse({"error": f"Could not extract a value. Got: {raw}", "screenshot_url": screenshot_url})
    raw_stripped = raw.replace(",", "")
    match = re.search(r"\d+\.?\d*", raw_stripped)
    if match:
        return JSONResponse({"value": float(match.group()), "screenshot_url": screenshot_url})
    return JSONResponse({"error": f"Could not parse number from: {raw[:80]}", "screenshot_url": screenshot_url})


@router.get("/signals/{signal_id}/card", response_class=HTMLResponse)
async def get_signal_card(request: Request, signal_id: PydanticObjectId):
    from src.templates_config import templates
    signal = await Signal.get(signal_id)
    if not signal:
        return HTMLResponse(status_code=404)
    return templates.TemplateResponse(request, "partials/signal_card.html", {"signal": signal})


@router.post("/signals", response_class=HTMLResponse)
async def create_signal(
    request: Request,
    name: Annotated[str, Form()],
    source_url: Annotated[str, Form()],
    source_extraction_query: Annotated[str, Form()],
    chart_type: Annotated[str, Form()] = "line",
    interval_minutes: Annotated[int, Form()] = 60,
    source_initial_value: Annotated[str, Form()] = "",
):
    signal = Signal(
        name=name,
        source_url=source_url,
        source_extraction_query=source_extraction_query,
        chart_type=chart_type,
        interval_minutes=interval_minutes,
    )
    await signal.insert()

    if source_initial_value:
        try:
            initial_value = float(source_initial_value)
            from src.models.signal_run import RunStatus
            run = SignalRun(
                signal_id=signal.id,
                value=initial_value,
                alert_triggered=False,
                status=RunStatus.OK,
                raw_result="verified at creation",
            )
            await run.insert()
            signal.last_value = initial_value
            await signal.save()
        except ValueError:
            pass

    schedule_signal(signal)

    if request.headers.get("HX-Request"):
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = "/app"
        return response
    return RedirectResponse(url="/app", status_code=303)


@router.post("/signals/{signal_id}/delete")
async def delete_signal(signal_id: PydanticObjectId):
    signal = await Signal.get(signal_id)
    if signal:
        unschedule_signal(str(signal_id))
        await SignalRun.find(SignalRun.signal_id == signal.id).delete()
        await signal.delete()
    return RedirectResponse(url="/app", status_code=303)


@router.post("/signals/{signal_id}/toggle-alert", response_class=HTMLResponse)
async def toggle_alert(request: Request, signal_id: PydanticObjectId):
    from src.templates_config import templates
    signal = await Signal.get(signal_id)
    if not signal:
        return HTMLResponse(status_code=404)
    signal.alert_enabled = not signal.alert_enabled
    await signal.save()
    return templates.TemplateResponse(request, "partials/signal_card.html", {"signal": signal})


@router.post("/signals/{signal_id}/toggle-alert-page")
async def toggle_alert_page(signal_id: PydanticObjectId):
    signal = await Signal.get(signal_id)
    if signal:
        signal.alert_enabled = not signal.alert_enabled
        await signal.save()
    return RedirectResponse(url=f"/app/signals/{signal_id}", status_code=303)


@router.post("/signals/{signal_id}/run-now", response_class=HTMLResponse)
async def run_now(request: Request, signal_id: PydanticObjectId):
    import asyncio
    from src.templates_config import templates
    from src.services.scheduler import _run_signal_job
    signal = await Signal.get(signal_id)
    if not signal:
        return HTMLResponse(status_code=404)
    asyncio.create_task(_run_signal_job(str(signal_id)))
    return templates.TemplateResponse(request, "partials/signal_card.html", {"signal": signal, "running": True})


@router.post("/signals/{signal_id}/update", response_class=HTMLResponse)
async def update_signal(
    request: Request,
    signal_id: PydanticObjectId,
    name: Annotated[str, Form()],
    interval_minutes: Annotated[int, Form()] = 60,
    source_extraction_query: Annotated[str, Form()] = "",
):
    from src.templates_config import templates
    signal = await Signal.get(signal_id)
    if not signal:
        return RedirectResponse(url="/app", status_code=303)

    signal.name = name
    signal.interval_minutes = interval_minutes
    if source_extraction_query:
        signal.source_extraction_query = source_extraction_query
    signal.consecutive_errors = 0
    signal.status = SignalStatus.ACTIVE
    await signal.save()
    schedule_signal(signal)

    runs = await SignalRun.find(SignalRun.signal_id == signal.id).sort("-ran_at").limit(20).to_list()
    return templates.TemplateResponse(request, "signal_detail.html", {"signal": signal, "runs": runs})
```

**Step 2: Run all tests**

```bash
uv run pytest tests/ -v
```
Expected: All pass

**Step 3: Commit**

```bash
git add src/routes/signals.py
git commit -m "refactor: rewrite signal routes — add preview endpoint, remove chat/discovery"
```

---

### Task 5: Rewrite create_modal.html as flip card

**Files:**
- Modify: `src/templates/partials/create_modal.html`

**Step 1: Replace entire file content**

Keep the modal shell (backdrop, header with "NEW SIGNAL" + close button) identical.
Replace all phase content with a single flip card using CSS 3D transforms.

```html
<div id="create-modal"
     class="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50"
     onclick="if(event.target===this) this.remove()">
  <div class="bg-dark-card border border-dark-border rounded-lg w-full max-w-xl mx-4 overflow-hidden" onclick="event.stopPropagation()">

    <!-- Header -->
    <div class="flex items-center justify-between px-6 py-4 border-b border-dark-border">
      <h2 class="font-bold text-white tracking-wider text-sm font-mono">NEW SIGNAL</h2>
      <button onclick="document.getElementById('create-modal').remove()"
        class="text-gray-600 hover:text-white transition-colors text-xl leading-none">×</button>
    </div>

    <!-- Flip card -->
    <div style="perspective: 1000px;">
      <div id="flip-inner" style="transition: transform 0.5s; transform-style: preserve-3d; position: relative; min-height: 360px;">

        <!-- FRONT: Form -->
        <div style="backface-visibility: hidden;" class="px-6 py-5 absolute inset-0">
          <div class="space-y-4">
            <div>
              <label class="block text-xs text-gray-600 font-mono mb-1">NAME</label>
              <input id="f-name" type="text" placeholder="e.g. BTC Price"
                class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50" />
            </div>
            <div>
              <label class="block text-xs text-gray-600 font-mono mb-1">URL</label>
              <input id="f-url" type="url" placeholder="https://..."
                class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50" />
            </div>
            <div>
              <label class="block text-xs text-gray-600 font-mono mb-1">WHAT TO EXTRACT</label>
              <input id="f-query" type="text" placeholder="e.g. current BTC price in USD"
                class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50" />
            </div>
            <div>
              <label class="block text-xs text-gray-600 font-mono mb-2">CHART TYPE</label>
              <div class="flex gap-6">
                <label class="flex items-center gap-2 text-xs font-mono text-gray-400 cursor-pointer">
                  <input type="radio" name="chart-type" value="line" checked class="accent-neon-green" /> Line
                </label>
                <label class="flex items-center gap-2 text-xs font-mono text-gray-400 cursor-pointer">
                  <input type="radio" name="chart-type" value="bar" class="accent-neon-green" /> Bar
                </label>
                <label class="flex items-center gap-2 text-xs font-mono text-gray-400 cursor-pointer">
                  <input type="radio" name="chart-type" value="flag" class="accent-neon-green" /> Flag (true/false)
                </label>
              </div>
            </div>
            <div>
              <label class="block text-xs text-gray-600 font-mono mb-1">CHECK INTERVAL</label>
              <select id="f-interval"
                class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50">
                <option value="60">1h</option>
                <option value="120">2h</option>
                <option value="360">6h</option>
                <option value="720">12h</option>
                <option value="1440">24h</option>
              </select>
            </div>
            <p id="dry-run-error" class="hidden text-red-400 text-xs font-mono"></p>
            <button id="dry-run-btn" onclick="runDryRun()"
              class="w-full py-2 bg-neon-green/10 border border-neon-green/30 text-neon-green text-xs font-mono rounded hover:bg-neon-green/20 transition-all">
              DRY RUN
            </button>
          </div>
        </div>

        <!-- BACK: Preview -->
        <div id="card-back" style="backface-visibility: hidden; transform: rotateY(180deg);" class="px-6 py-5 absolute inset-0">
          <div class="border border-dark-border rounded p-4 space-y-3 text-xs font-mono mb-5">
            <div class="text-gray-500 tracking-wider mb-3">PREVIEW RESULT</div>
            <div class="flex gap-3 items-center">
              <span class="text-gray-600 w-20 shrink-0">VALUE</span>
              <span id="preview-value" class="font-bold text-xl"></span>
            </div>
            <div class="flex gap-3">
              <span class="text-gray-600 w-20 shrink-0">SOURCE</span>
              <span id="preview-source" class="text-neon-blue break-all"></span>
            </div>
            <div id="preview-screenshot-row" class="flex gap-3 hidden">
              <span class="text-gray-600 w-20 shrink-0">SCREENSHOT</span>
              <a id="preview-screenshot" href="#" target="_blank" rel="noopener"
                class="text-neon-blue underline hover:text-white transition-colors">📸 view</a>
            </div>
          </div>

          <form id="save-form" method="POST" action="/signals"
                hx-post="/signals" hx-target="#create-modal" hx-swap="outerHTML">
            <input type="hidden" name="name" id="sf-name" />
            <input type="hidden" name="source_url" id="sf-url" />
            <input type="hidden" name="source_extraction_query" id="sf-query" />
            <input type="hidden" name="chart_type" id="sf-chart-type" />
            <input type="hidden" name="interval_minutes" id="sf-interval" />
            <input type="hidden" name="source_initial_value" id="sf-initial-value" />

            <div class="flex gap-3">
              <button type="button" onclick="flipBack()"
                class="flex-1 py-2 border border-dark-border text-gray-500 text-xs font-mono rounded hover:border-gray-500 hover:text-gray-300 transition-all">
                ← TRY AGAIN
              </button>
              <button type="submit"
                class="flex-1 py-2 bg-neon-green text-black font-bold text-xs rounded tracking-wider hover:bg-neon-green/90 transition-all">
                SAVE SIGNAL
              </button>
            </div>
          </form>
        </div>

      </div>
    </div>

  </div>
</div>

<script>
(function() {
  window.flipBack = function() {
    document.getElementById('flip-inner').style.transform = '';
    document.getElementById('dry-run-error').classList.add('hidden');
  };

  window.runDryRun = async function() {
    const url = document.getElementById('f-url').value.trim();
    const query = document.getElementById('f-query').value.trim();
    const name = document.getElementById('f-name').value.trim();
    const chartType = document.querySelector('input[name="chart-type"]:checked').value;
    const interval = document.getElementById('f-interval').value;
    const errEl = document.getElementById('dry-run-error');

    if (!url || !query) {
      errEl.textContent = 'URL and extraction query are required.';
      errEl.classList.remove('hidden');
      return;
    }

    const btn = document.getElementById('dry-run-btn');
    btn.disabled = true;
    btn.textContent = '⟳ RUNNING...';
    errEl.classList.add('hidden');

    let data;
    try {
      const res = await fetch('/signals/preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url, extraction_query: query, chart_type: chartType }),
      });
      data = await res.json();
    } catch (e) {
      errEl.textContent = '⚠ Connection error. Please try again.';
      errEl.classList.remove('hidden');
      btn.disabled = false;
      btn.textContent = 'DRY RUN';
      return;
    }

    btn.disabled = false;
    btn.textContent = 'DRY RUN';

    if (data.error) {
      errEl.textContent = '⚠ ' + data.error;
      errEl.classList.remove('hidden');
      return;
    }

    // Populate back face
    const valueEl = document.getElementById('preview-value');
    if (chartType === 'flag') {
      valueEl.textContent = data.flag ? '✓ TRUE' : '✗ FALSE';
      valueEl.className = 'font-bold text-xl ' + (data.flag ? 'text-neon-green' : 'text-red-400');
    } else {
      valueEl.textContent = data.value;
      valueEl.className = 'font-bold text-xl text-neon-green';
    }
    document.getElementById('preview-source').textContent = url.replace(/^https?:\/\//, '');
    if (data.screenshot_url) {
      document.getElementById('preview-screenshot').href = data.screenshot_url;
      document.getElementById('preview-screenshot-row').classList.remove('hidden');
    }

    // Populate hidden save form fields
    document.getElementById('sf-name').value = name || new URL(url).hostname;
    document.getElementById('sf-url').value = url;
    document.getElementById('sf-query').value = query;
    document.getElementById('sf-chart-type').value = chartType;
    document.getElementById('sf-interval').value = interval;
    document.getElementById('sf-initial-value').value = data.value != null ? data.value : '';

    document.getElementById('flip-inner').style.transform = 'rotateY(180deg)';
  };
})();
</script>
```

**Step 2: Commit**

```bash
git add src/templates/partials/create_modal.html
git commit -m "feat: replace chat+discovery modal with simple flip-card dry-run form"
```

---

### Task 6: Update signal_card.html and signal_detail.html

**Files:**
- Modify: `src/templates/partials/signal_card.html`
- Modify: `src/templates/signal_detail.html`

**Step 1: Update `signal_card.html`**

Three changes:
1. Replace `signal.prompt[:80]` with the source URL domain
2. Replace the value display block to handle flag type
3. Remove `signal.parsed.unit` reference

The current value block (lines 27–33):
```html
<div class="flex items-end gap-1 mb-4">
  {% if signal.last_value is not none %}
  <span class="text-2xl font-bold text-neon-blue">{{ "%.2f" | format(signal.last_value) }}</span>
  {% if signal.parsed.unit %}<span class="text-gray-500 text-xs mb-1">{{ signal.parsed.unit }}</span>{% endif %}
  {% else %}
  <span class="text-gray-600 text-sm font-mono">— no data yet —</span>
  {% endif %}
</div>
```

Replace with:
```html
<div class="flex items-end gap-1 mb-4">
  {% if signal.last_value is not none %}
    {% if signal.chart_type == 'flag' %}
      <span class="text-2xl font-bold {% if signal.last_value == 1.0 %}text-neon-green{% else %}text-red-400{% endif %}">
        {% if signal.last_value == 1.0 %}✓ TRUE{% else %}✗ FALSE{% endif %}
      </span>
    {% else %}
      <span class="text-2xl font-bold text-neon-blue">{{ "%.2f" | format(signal.last_value) }}</span>
    {% endif %}
  {% else %}
  <span class="text-gray-600 text-sm font-mono">— no data yet —</span>
  {% endif %}
</div>
```

Replace the prompt line (line 23):
```html
<p class="text-gray-500 text-xs font-mono mb-4 leading-relaxed border-l-2 border-dark-border pl-3">
  {{ signal.prompt[:80] }}{% if signal.prompt | length > 80 %}...{% endif %}
</p>
```
With:
```html
<p class="text-gray-500 text-xs font-mono mb-4 leading-relaxed border-l-2 border-dark-border pl-3">
  {{ signal.source_extraction_query[:80] }}{% if signal.source_extraction_query | length > 80 %}...{% endif %}
</p>
```

**Step 2: Update `signal_detail.html`**

Key changes:
1. Remove `signal.parsed.unit` from value display (line 27)
2. Remove condition line (line 33)
3. Remove `signal.description` block (lines 35–37)
4. Remove `signal.metric_description` block (lines 38–40)
5. Remove `signal.conversation_history` block (lines 82–100)
6. Update value display to handle flag type
7. Update EDIT SIGNAL form: replace `prompt` textarea with `name` + `source_extraction_query` fields
8. Update Chart.js script: replace `signal.parsed.topic` with `signal.name`, remove threshold lines, use `signal.chart_type` for chart type
9. Keep source URL link as-is (already uses `signal.source_url`)

Updated value display block (replace lines 24–32):
```html
{% if signal.last_value is not none %}
<div class="flex items-end gap-1 mt-4">
  {% if signal.chart_type == 'flag' %}
  <span class="text-4xl font-bold {% if signal.last_value == 1.0 %}text-neon-green{% else %}text-red-400{% endif %}">
    {% if signal.last_value == 1.0 %}✓ TRUE{% else %}✗ FALSE{% endif %}
  </span>
  {% else %}
  <span class="text-4xl font-bold text-neon-blue">{{ "%.2f" | format(signal.last_value) }}</span>
  {% endif %}
</div>
{% else %}
<p class="text-gray-600 text-sm font-mono mt-4">No data yet</p>
{% endif %}
```

Updated EDIT SIGNAL form (replace the form block):
```html
<form method="POST" action="/signals/{{ signal.id }}/update">
  <label class="block text-xs text-gray-600 font-mono mb-1">NAME</label>
  <input name="name" value="{{ signal.name }}" required
    class="w-full bg-dark-bg border border-dark-border rounded p-3 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50 mb-4" />

  <label class="block text-xs text-gray-600 font-mono mb-1">WHAT TO EXTRACT</label>
  <textarea name="source_extraction_query" rows="2"
    class="w-full bg-dark-bg border border-dark-border rounded p-3 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50 resize-none mb-4">{{ signal.source_extraction_query }}</textarea>

  <label class="block text-xs text-gray-600 font-mono mb-1">CHECK INTERVAL</label>
  <select name="interval_minutes"
    class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50 mb-4">
    {% for hours in [1, 2, 6, 12, 24] %}
    <option value="{{ hours * 60 }}" {% if signal.interval_minutes == hours * 60 %}selected{% endif %}>{{ hours }}h</option>
    {% endfor %}
  </select>

  <button type="submit" class="w-full py-2 bg-neon-green/10 border border-neon-green/30 text-neon-green text-xs font-mono rounded hover:bg-neon-green/20 transition-all">SAVE</button>
</form>
```

Updated Chart.js script block (replace the `{% block scripts %}` section):
```html
{% block scripts %}
{% set chart_runs = runs | selectattr('value', 'ne', none) | list %}
{% if chart_runs and signal.chart_type != 'flag' %}
<script>
const ctx = document.getElementById('signalChart').getContext('2d');
const labels = [{% for run in chart_runs | reverse %}"{{ run.ran_at | strftime('%m/%d %H:%M') }}"{% if not loop.last %},{% endif %}{% endfor %}];
const data = [{% for run in chart_runs | reverse %}{{ run.value }}{% if not loop.last %},{% endif %}{% endfor %}];

new Chart(ctx, {
  type: '{{ signal.chart_type }}',
  data: {
    labels,
    datasets: [{
      label: '{{ signal.name }}',
      data,
      borderColor: '#00cfff',
      backgroundColor: 'rgba(0, 207, 255, 0.05)',
      borderWidth: 2,
      pointBackgroundColor: '#00cfff',
      pointRadius: 3,
      tension: 0.3,
      fill: true,
    }]
  },
  options: {
    responsive: true,
    plugins: {
      legend: { display: false },
      tooltip: {
        backgroundColor: '#12121a',
        borderColor: '#1e1e2e',
        borderWidth: 1,
        titleColor: '#9ca3af',
        bodyColor: '#00cfff',
        titleFont: { family: 'JetBrains Mono', size: 11 },
        bodyFont: { family: 'JetBrains Mono', size: 13, weight: 'bold' },
      }
    },
    scales: {
      x: { grid: { color: '#1e1e2e' }, ticks: { color: '#6b7280', font: { family: 'JetBrains Mono', size: 10 } } },
      y: { grid: { color: '#1e1e2e' }, ticks: { color: '#6b7280', font: { family: 'JetBrains Mono', size: 10 } } }
    }
  }
});
</script>
{% endif %}
{% endblock %}
```

**Step 3: Run all tests**

```bash
uv run pytest tests/ -v
```
Expected: All pass

**Step 4: Commit**

```bash
git add src/templates/partials/signal_card.html src/templates/signal_detail.html
git commit -m "feat: update signal card and detail page for simplified model"
```

---

### Task 7: Final cleanup — remove stale pyproject.toml entries if any

**Files:**
- Check: `pyproject.toml`

**Step 1: Check for removed dependencies**

The deleted files used: `duckduckgo_search` (if present), any LLM-specific packages. `httpx` stays (used by tracing.py). Run:

```bash
grep -r "duckduckgo\|ddgs" pyproject.toml
```

Remove any matches found. `httpx` stays.

**Step 2: Run all tests one final time**

```bash
uv run pytest tests/ -v
```
Expected: All pass

**Step 3: Final commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: remove stale dependencies after simplification"
```
