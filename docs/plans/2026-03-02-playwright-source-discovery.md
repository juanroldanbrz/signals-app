# Playwright Source Discovery — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace DuckDuckGo text search with a one-time Playwright-based source discovery that finds the real URL and DOM element for a metric, storing a reusable screenshot+Gemini extraction config on the signal.

**Architecture:** A new `discovery.py` service runs Playwright async to navigate to the best URL (via DuckDuckGo or user hint), asks Gemini to find a CSS selector, screenshots the element (or full page), and has Gemini vision extract the live value. Result is stored on `Signal` as `source_url`, `source_selector`, `source_extraction_query`. The `executor.py` runtime path uses these fields directly on every scheduled run — no more DuckDuckGo per run. Old signals without `source_url` keep the legacy DuckDuckGo fallback.

**Tech Stack:** FastAPI, Playwright (playwright-python async), Google Gemini (`google-genai` with vision), Beanie/MongoDB, HTMX, vanilla JS.

---

### Task 1: Add playwright dependency and install browser

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add playwright to dependencies**

Run:
```bash
cd /Users/juanroldan/develop/signals-app
uv add playwright
```

Expected: `pyproject.toml` and `uv.lock` updated, playwright installed in `.venv`.

**Step 2: Install Chromium browser**

Run:
```bash
uv run playwright install chromium
```

Expected: Chromium downloaded and installed (output ends with "chromium ✓").

**Step 3: Verify**

```bash
uv run python -c "from playwright.async_api import async_playwright; print('OK')"
```

Expected: `OK`

**Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat: add playwright dependency"
```

---

### Task 2: Extend Signal model with source fields

**Files:**
- Modify: `src/models/signal.py`

**Step 1: Add 4 new fields to `Signal`** after `dashboard_chart_type`:

```python
source_url: str | None = None
source_selector: str | None = None
source_extraction_query: str | None = None
source_verified: bool = False
```

Full updated `Signal` class fields (replace from `name:` through `class Settings`):

```python
class Signal(Document):
    name: str
    prompt: str
    parsed: ParsedSignal
    interval_minutes: int = 60
    alert_enabled: bool = True
    status: SignalStatus = SignalStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_run_at: datetime | None = None
    last_value: float | None = None
    alert_triggered: bool = False
    consecutive_errors: int = 0
    description: str | None = None
    metric_description: str | None = None
    conversation_history: list[ChatTurn] = Field(default_factory=list)
    dashboard_chart_type: Literal["line", "bar", "gauge"] = "line"
    source_url: str | None = None
    source_selector: str | None = None
    source_extraction_query: str | None = None
    source_verified: bool = False

    class Settings:
        name = "signals"
```

**Step 2: Verify**

```bash
cd /Users/juanroldan/develop/signals-app
uv run python -c "from src.models.signal import Signal; print('OK')"
```

Expected: `OK`

**Step 3: Commit**

```bash
git add src/models/signal.py
git commit -m "feat: add source_url, source_selector, source_extraction_query, source_verified to Signal"
```

---

### Task 3: Create discovery service

**Files:**
- Create: `src/services/discovery.py`

**Step 1: Create the file with this exact content**

```python
import re
from urllib.parse import urlparse, urlunparse
from pydantic import BaseModel
from google import genai
from google.genai import types as genai_types
from playwright.async_api import async_playwright
from src.config import settings


class DiscoveryResult(BaseModel):
    success: bool
    url: str | None = None
    selector: str | None = None
    extraction_query: str | None = None
    value: float | None = None
    error: str | None = None


def _clean_url(url: str) -> str:
    """Strip query params and fragments to get a canonical URL."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


async def _find_selector(html: str, topic: str) -> str | None:
    """Ask Gemini to identify the CSS selector most likely containing the metric value."""
    client = genai.Client(api_key=settings.gemini_api_key)
    prompt = (
        f"Given this HTML, return ONLY the single CSS selector (e.g. '#price', '.current-price', 'span.value') "
        f"that most likely contains the current numeric value for '{topic}'.\n"
        f"Rules:\n"
        f"- Return ONLY the selector string, nothing else\n"
        f"- If you cannot identify a reliable selector, return null\n"
        f"- Prefer IDs over classes, specific over generic\n\n"
        f"HTML (truncated):\n{html[:8000]}"
    )
    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
    )
    raw = response.text.strip().strip('"').strip("'")
    if raw.lower() in ("null", "none", ""):
        return None
    return raw


async def _extract_value_from_screenshot(screenshot: bytes, query: str) -> float | None:
    """Send a screenshot to Gemini vision and extract the numeric value."""
    client = genai.Client(api_key=settings.gemini_api_key)
    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            genai_types.Part.from_bytes(data=screenshot, mime_type="image/png"),
            (
                f"{query}\n"
                f"Return ONLY the number (e.g. 67432.10), no units, no text.\n"
                f"If you cannot find a clear numeric value, return null."
            ),
        ],
    )
    raw = response.text.strip()
    if raw.lower() in ("null", "none", ""):
        return None
    raw_stripped = raw.replace(",", "")
    match = re.search(r"\d+\.?\d*", raw_stripped)
    if match:
        try:
            return float(match.group())
        except ValueError:
            return None
    return None


async def _search_for_url(search_query: str) -> str | None:
    """Use DuckDuckGo to find the best URL for the search query."""
    from duckduckgo_search import DDGS
    import asyncio

    loop = asyncio.get_running_loop()

    def _search():
        with DDGS() as ddgs:
            results = list(ddgs.text(search_query, max_results=3))
        return results

    results = await loop.run_in_executor(None, _search)
    if not results:
        return None
    return results[0].get("href") or results[0].get("url")


async def discover_source(
    topic: str,
    search_query: str,
    url_hint: str | None = None,
) -> DiscoveryResult:
    """
    Discover the data source for a metric.

    1. Find URL (url_hint or DuckDuckGo)
    2. Navigate with Playwright
    3. Ask Gemini for CSS selector from HTML
    4. Screenshot selector element (or full page if no selector)
    5. Ask Gemini vision to extract the value
    """
    extraction_query = f"What is the current numeric value for {topic} shown in this image?"

    # Step 1: Find URL
    if url_hint:
        url = url_hint.strip()
        if not url.startswith("http"):
            url = "https://" + url
    else:
        url = await _search_for_url(search_query)
        if not url:
            return DiscoveryResult(success=False, error="Could not find a URL via search.")

    clean_url = _clean_url(url)

    # Steps 2-5: Playwright session
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=20000)

            # Step 3: Try to find a CSS selector
            html = await page.content()
            selector = await _find_selector(html, topic)

            # Validate selector exists in DOM
            if selector:
                try:
                    element = page.locator(selector).first
                    await element.wait_for(timeout=3000)
                except Exception:
                    selector = None  # selector not found in DOM, fall back to full page

            # Step 4: Screenshot
            if selector:
                try:
                    element = page.locator(selector).first
                    screenshot = await element.screenshot(type="png")
                except Exception:
                    selector = None
                    screenshot = await page.screenshot(type="png", full_page=False)
            else:
                screenshot = await page.screenshot(type="png", full_page=False)

            await browser.close()

    except Exception as e:
        return DiscoveryResult(success=False, error=f"Browser error: {str(e)[:200]}")

    # Step 5: Extract value from screenshot
    value = await _extract_value_from_screenshot(screenshot, extraction_query)

    if value is None:
        return DiscoveryResult(
            success=False,
            url=clean_url,
            selector=selector,
            extraction_query=extraction_query,
            error="Could not extract a numeric value from the page.",
        )

    return DiscoveryResult(
        success=True,
        url=clean_url,
        selector=selector,
        extraction_query=extraction_query,
        value=value,
    )
```

**Step 2: Verify import**

```bash
cd /Users/juanroldan/develop/signals-app
uv run python -c "from src.services.discovery import discover_source, DiscoveryResult; print('OK')"
```

Expected: `OK`

**Step 3: Commit**

```bash
git add src/services/discovery.py
git commit -m "feat: add Playwright source discovery service"
```

---

### Task 4: Add POST /signals/discover endpoint + extend POST /signals

**Files:**
- Modify: `src/routes/signals.py`

**Step 1: Add `DiscoverRequest` model and `/signals/discover` route**

Add after the `ChatRequest` class and `chat_turn` route (after line 25), before `create_signal`:

```python
class DiscoverRequest(PydanticBaseModel):
    topic: str
    search_query: str
    url_hint: str | None = None


@router.post("/signals/discover")
async def discover_signal_source(body: DiscoverRequest):
    from src.services.discovery import discover_source
    from fastapi.responses import JSONResponse
    result = await discover_source(
        topic=body.topic,
        search_query=body.search_query,
        url_hint=body.url_hint,
    )
    return JSONResponse(result.model_dump())
```

**Step 2: Extend `create_signal` to accept source fields**

Add these 4 form parameters to `create_signal` after `conversation_history_json`:

```python
source_url: Annotated[str, Form()] = "",
source_selector: Annotated[str, Form()] = "",
source_extraction_query: Annotated[str, Form()] = "",
source_verified: Annotated[str, Form()] = "false",
```

Update the `Signal(...)` constructor call to include them:

```python
signal = Signal(
    name=name or parsed.topic.title(),
    prompt=prompt,
    parsed=parsed,
    interval_minutes=interval_minutes,
    description=description or None,
    metric_description=metric_description or None,
    conversation_history=history,
    dashboard_chart_type=dashboard_chart_type,
    source_url=source_url or None,
    source_selector=source_selector or None,
    source_extraction_query=source_extraction_query or None,
    source_verified=source_verified.lower() == "true",
)
```

**Step 3: Verify routes registered**

```bash
cd /Users/juanroldan/develop/signals-app
uv run python -c "
from src.routes.signals import router
paths = [r.path for r in router.routes]
assert '/signals/discover' in paths
print('OK:', paths)
"
```

Expected: `OK` with list including `/signals/discover`

**Step 4: Commit**

```bash
git add src/routes/signals.py
git commit -m "feat: add POST /signals/discover endpoint and source fields to POST /signals"
```

---

### Task 5: Update executor.py to use stored source config

**Files:**
- Modify: `src/services/executor.py`

**Step 1: Replace `run_signal` with a version that uses source config when available**

Replace the entire `run_signal` function (lines 56-99) with:

```python
async def _screenshot_and_extract(url: str, selector: str | None, extraction_query: str) -> tuple[float | None, str]:
    """Navigate to url, screenshot selector or full page, extract value via Gemini vision."""
    from playwright.async_api import async_playwright
    from google.genai import types as genai_types

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            await page.goto(url, wait_until="networkidle", timeout=20000)

            if selector:
                try:
                    element = page.locator(selector).first
                    await element.wait_for(timeout=3000)
                    screenshot = await element.screenshot(type="png")
                except Exception:
                    screenshot = await page.screenshot(type="png", full_page=False)
            else:
                screenshot = await page.screenshot(type="png", full_page=False)

            await browser.close()
    except Exception as e:
        return None, f"Browser error: {str(e)[:200]}"

    client = genai.Client(api_key=settings.gemini_api_key)
    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash",
        contents=[
            genai_types.Part.from_bytes(data=screenshot, mime_type="image/png"),
            (
                f"{extraction_query}\n"
                f"Return ONLY the number (e.g. 67432.10), no units, no text.\n"
                f"If you cannot find a clear numeric value, return null."
            ),
        ],
    )
    raw = response.text.strip()
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


async def run_signal(signal) -> dict:
    """Run one check cycle for a signal."""

    # New path: use stored source config (Playwright + Gemini vision)
    if signal.source_url and signal.source_extraction_query:
        value, raw_result = await _screenshot_and_extract(
            url=signal.source_url,
            selector=signal.source_selector,
            extraction_query=signal.source_extraction_query,
        )

        if value is None:
            return {
                "value": None,
                "alert_triggered": False,
                "raw_result": raw_result,
                "status": "error",
            }

        triggered = evaluate_condition(value, signal.parsed.condition, signal.parsed.threshold)
        return {
            "value": value,
            "alert_triggered": triggered,
            "raw_result": raw_result,
            "status": "triggered" if triggered else "ok",
        }

    # Legacy fallback: DuckDuckGo + text extraction (for signals without source_url)
    from src.services.search import search_web

    raw_result = await search_web(signal.parsed.search_query)

    if not raw_result:
        return {
            "value": None,
            "alert_triggered": False,
            "raw_result": "No search results found.",
            "status": "error",
        }

    if signal.parsed.condition == "contains":
        triggered = evaluate_condition(
            None, "contains", None,
            text=raw_result, topic=signal.parsed.topic
        )
        return {
            "value": None,
            "alert_triggered": triggered,
            "raw_result": raw_result,
            "status": "triggered" if triggered else "ok",
        }

    value = await extract_value_from_text(signal.parsed.topic, raw_result)

    if value is None:
        return {
            "value": None,
            "alert_triggered": False,
            "raw_result": raw_result,
            "status": "error",
        }

    triggered = evaluate_condition(value, signal.parsed.condition, signal.parsed.threshold)
    return {
        "value": value,
        "alert_triggered": triggered,
        "raw_result": raw_result,
        "status": "triggered" if triggered else "ok",
    }
```

**Step 2: Verify import**

```bash
cd /Users/juanroldan/develop/signals-app
uv run python -c "from src.services.executor import run_signal; print('OK')"
```

Expected: `OK`

**Step 3: Commit**

```bash
git add src/services/executor.py
git commit -m "feat: use Playwright screenshot path in executor when source_url is set"
```

---

### Task 6: Update create_modal.html with Phase 1.5 discovery UI

**Files:**
- Modify: `src/templates/partials/create_modal.html`

**Step 1: Replace the entire file** with this content that adds Phase 1.5 (discovery) between chat and confirmation:

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

    <!-- PHASE 1: Chat terminal -->
    <div id="chat-phase">
      <div id="chat-log" class="px-6 py-4 space-y-3 min-h-[180px] max-h-72 overflow-y-auto font-mono text-sm">
      </div>
      <div class="px-6 pb-5 border-t border-dark-border pt-4">
        <div class="flex items-center gap-2">
          <span class="text-neon-green font-mono text-sm select-none">&gt;</span>
          <input id="chat-input"
            type="text"
            placeholder="type your answer..."
            autocomplete="off"
            class="flex-1 bg-transparent border-none outline-none text-gray-200 font-mono text-sm placeholder-gray-700 caret-neon-green" />
          <span id="chat-spinner" class="hidden text-neon-green text-xs font-mono animate-pulse">THINKING...</span>
          <button id="chat-send"
            class="px-3 py-1 bg-neon-green/10 border border-neon-green/30 text-neon-green text-xs font-mono rounded hover:bg-neon-green/20 transition-all">
            SEND
          </button>
        </div>
      </div>
    </div>

    <!-- PHASE 1.5: Discovery -->
    <div id="discovery-phase" class="hidden px-6 py-5 font-mono">
      <div id="discovery-log" class="space-y-3 min-h-[120px] max-h-64 overflow-y-auto text-sm mb-4">
      </div>
      <div id="discovery-input-row" class="hidden border-t border-dark-border pt-4">
        <div class="flex items-center gap-2">
          <span class="text-neon-green font-mono text-sm select-none">&gt;</span>
          <input id="discovery-input"
            type="text"
            placeholder="enter a website URL..."
            autocomplete="off"
            class="flex-1 bg-transparent border-none outline-none text-gray-200 font-mono text-sm placeholder-gray-700 caret-neon-green" />
          <button id="discovery-send"
            class="px-3 py-1 bg-neon-green/10 border border-neon-green/30 text-neon-green text-xs font-mono rounded hover:bg-neon-green/20 transition-all">
            TRY
          </button>
        </div>
      </div>
    </div>

    <!-- PHASE 2: Confirmation card -->
    <div id="confirm-phase" class="hidden px-6 py-5 font-mono">
      <div class="border border-dark-border rounded p-4 space-y-2 text-xs mb-5">
        <div class="text-gray-500 tracking-wider mb-3">SIGNAL SPEC</div>
        <div class="flex gap-3"><span class="text-gray-600 w-24 shrink-0">NAME</span><span id="spec-name" class="text-white"></span></div>
        <div class="flex gap-3"><span class="text-gray-600 w-24 shrink-0">METRIC</span><span id="spec-metric" class="text-gray-300 break-words"></span></div>
        <div class="flex gap-3"><span class="text-gray-600 w-24 shrink-0">ALERT</span><span id="spec-alert" class="text-gray-300"></span></div>
        <div class="flex gap-3"><span class="text-gray-600 w-24 shrink-0">DASHBOARD</span><span id="spec-dashboard" class="text-gray-300"></span></div>
        <div class="flex gap-3"><span class="text-gray-600 w-24 shrink-0">INTERVAL</span><span id="spec-interval" class="text-gray-300"></span></div>
        <div class="flex gap-3"><span class="text-gray-600 w-24 shrink-0">SOURCE</span><span id="spec-source" class="text-neon-blue break-all"></span></div>
        <div class="flex gap-3"><span class="text-gray-600 w-24 shrink-0">VALUE</span><span id="spec-value" class="text-neon-green font-bold"></span></div>
      </div>

      <form id="confirm-form" method="POST" action="/signals"
            hx-post="/signals"
            hx-target="#create-modal"
            hx-swap="outerHTML">
        <input type="hidden" name="prompt" id="f-prompt" />
        <input type="hidden" name="name" id="f-name" />
        <input type="hidden" name="description" id="f-description" />
        <input type="hidden" name="metric_description" id="f-metric-description" />
        <input type="hidden" name="dashboard_chart_type" id="f-chart-type" />
        <input type="hidden" name="topic" id="f-topic" />
        <input type="hidden" name="condition" id="f-condition" />
        <input type="hidden" name="threshold" id="f-threshold" />
        <input type="hidden" name="unit" id="f-unit" />
        <input type="hidden" name="search_query" id="f-search-query" />
        <input type="hidden" name="interval_minutes" id="f-interval" />
        <input type="hidden" name="conversation_history_json" id="f-history" />
        <input type="hidden" name="source_url" id="f-source-url" />
        <input type="hidden" name="source_selector" id="f-source-selector" />
        <input type="hidden" name="source_extraction_query" id="f-source-extraction-query" />
        <input type="hidden" name="source_verified" id="f-source-verified" value="false" />

        <div class="flex gap-3">
          <button type="button" onclick="reviseSignal()"
            class="flex-1 py-2 border border-dark-border text-gray-500 text-xs font-mono rounded hover:border-gray-500 hover:text-gray-300 transition-all">
            ← REVISE
          </button>
          <button type="submit"
            class="flex-1 py-2 bg-neon-green text-black font-bold text-xs rounded tracking-wider hover:bg-neon-green/90 transition-all">
            CONFIRM &amp; CREATE
          </button>
        </div>
      </form>
    </div>

  </div>
</div>

<script>
(function() {
  let history = [];
  let currentSpec = null;
  let currentDiscovery = null;

  // --- Chat phase helpers ---

  function appendMessage(role, text) {
    const log = document.getElementById('chat-log');
    const div = document.createElement('div');
    div.className = 'flex gap-2';
    const prefix = document.createElement('span');
    prefix.className = role === 'agent'
      ? 'text-neon-green font-bold shrink-0'
      : 'text-gray-600 font-bold shrink-0';
    prefix.textContent = role === 'agent' ? '[AGENT]' : '[YOU]';
    const msg = document.createElement('span');
    msg.className = role === 'agent'
      ? 'text-gray-300 whitespace-pre-wrap'
      : 'text-gray-400 whitespace-pre-wrap';
    msg.textContent = text;
    div.appendChild(prefix);
    div.appendChild(msg);
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  async function sendMessage(text) {
    if (!text.trim()) return;
    appendMessage('user', text);
    history.push({ role: 'user', content: text });

    const input = document.getElementById('chat-input');
    const spinner = document.getElementById('chat-spinner');
    const sendBtn = document.getElementById('chat-send');
    input.disabled = true;
    sendBtn.disabled = true;
    spinner.classList.remove('hidden');

    let data = null;
    try {
      const res = await fetch('/signals/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history: history.slice(0, -1), message: text }),
      });
      data = await res.json();

      appendMessage('agent', data.message);
      history.push({ role: 'agent', content: data.message });

      if (data.done && data.spec) {
        currentSpec = data.spec;
        setTimeout(startDiscovery, 400);
      }
    } catch (e) {
      appendMessage('agent', '⚠ Connection error. Please try again.');
    } finally {
      spinner.classList.add('hidden');
      if (!data || !data.done) {
        input.disabled = false;
        sendBtn.disabled = false;
        input.value = '';
        input.focus();
      }
    }
  }

  // --- Discovery phase helpers ---

  function appendDiscovery(text, color) {
    const log = document.getElementById('discovery-log');
    const div = document.createElement('div');
    div.className = 'flex gap-2 text-xs';
    const msg = document.createElement('span');
    msg.className = (color || 'text-gray-400') + ' font-mono whitespace-pre-wrap';
    msg.textContent = text;
    div.appendChild(msg);
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  async function runDiscovery(urlHint) {
    const inputRow = document.getElementById('discovery-input-row');
    inputRow.classList.add('hidden');

    appendDiscovery('⟳ SCANNING SOURCE...', 'text-neon-green animate-pulse');

    let result = null;
    try {
      const body = {
        topic: currentSpec.topic,
        search_query: currentSpec.search_query,
      };
      if (urlHint) body.url_hint = urlHint;

      const res = await fetch('/signals/discover', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      result = await res.json();
    } catch (e) {
      appendDiscovery('⚠ Connection error during discovery.', 'text-red-400');
      showDiscoveryRetry();
      return;
    }

    // Remove the scanning line
    const log = document.getElementById('discovery-log');
    log.removeChild(log.lastChild);

    if (result.success) {
      currentDiscovery = result;
      const host = result.url.replace(/^https?:\/\//, '').split('/')[0];
      appendDiscovery('Found: ' + result.url, 'text-neon-blue');
      appendDiscovery('Current value: ' + result.value + (currentSpec.unit ? ' ' + currentSpec.unit : ''), 'text-white');
      appendDiscovery('');
      appendDiscovery('Is this the right source?', 'text-gray-300');
      appendDiscovery('[A] Yes — confirm   [B] No — suggest a different site', 'text-gray-500');

      // Wire up A/B response via discovery input
      showDiscoveryConfirmChoice();
    } else {
      appendDiscovery('⚠ ' + (result.error || 'Could not extract data from this page.'), 'text-red-400');
      appendDiscovery('Which website should I check instead?', 'text-gray-300');
      showDiscoveryRetry();
    }
  }

  function showDiscoveryConfirmChoice() {
    const input = document.getElementById('discovery-input');
    const sendBtn = document.getElementById('discovery-send');
    const inputRow = document.getElementById('discovery-input-row');
    input.placeholder = 'type A to confirm or B to suggest a site...';
    inputRow.classList.remove('hidden');
    input.focus();

    // One-time handler for A/B choice
    function handleChoice() {
      const val = input.value.trim().toUpperCase();
      if (val === 'A') {
        input.removeEventListener('keydown', onKey);
        sendBtn.removeEventListener('click', onClick);
        showConfirmPhase();
      } else if (val === 'B' || val !== '') {
        input.removeEventListener('keydown', onKey);
        sendBtn.removeEventListener('click', onClick);
        const hint = val === 'B' ? null : input.value.trim();
        input.value = '';
        input.placeholder = 'enter a website URL...';
        if (hint && hint !== 'B') {
          runDiscovery(hint);
        } else {
          appendDiscovery('Which website should I check?', 'text-gray-300');
          showDiscoveryRetry();
        }
      }
    }

    function onKey(e) { if (e.key === 'Enter') handleChoice(); }
    function onClick() { handleChoice(); }
    input.addEventListener('keydown', onKey);
    sendBtn.addEventListener('click', onClick);
  }

  function showDiscoveryRetry() {
    const input = document.getElementById('discovery-input');
    const inputRow = document.getElementById('discovery-input-row');
    input.placeholder = 'enter a website URL...';
    inputRow.classList.remove('hidden');
    input.value = '';
    input.focus();

    function handleRetry() {
      const url = input.value.trim();
      if (!url) return;
      input.removeEventListener('keydown', onKey);
      document.getElementById('discovery-send').removeEventListener('click', onClick);
      input.value = '';
      runDiscovery(url);
    }

    function onKey(e) { if (e.key === 'Enter') handleRetry(); }
    function onClick() { handleRetry(); }
    input.addEventListener('keydown', onKey);
    document.getElementById('discovery-send').addEventListener('click', onClick);
  }

  function startDiscovery() {
    document.getElementById('chat-phase').classList.add('hidden');
    document.getElementById('discovery-phase').classList.remove('hidden');
    runDiscovery(null);
  }

  // --- Confirmation phase ---

  function showConfirmPhase() {
    const s = currentSpec;
    const d = currentDiscovery;

    document.getElementById('discovery-phase').classList.add('hidden');
    document.getElementById('confirm-phase').classList.remove('hidden');

    document.getElementById('spec-name').textContent = s.name;
    document.getElementById('spec-metric').textContent = s.metric_description;
    const alertText = s.threshold != null
      ? 'triggers when ' + s.topic + ' ' + s.condition + ' ' + s.threshold + (s.unit ? ' ' + s.unit : '')
      : 'dashboard only — no alert';
    document.getElementById('spec-alert').textContent = alertText;
    const chartType = s.dashboard_chart_type || 'line';
    document.getElementById('spec-dashboard').textContent =
      chartType.charAt(0).toUpperCase() + chartType.slice(1) + ' chart';
    document.getElementById('spec-interval').textContent = 'every ' + Math.round(s.interval_minutes / 60) + 'h';
    document.getElementById('spec-source').textContent = d ? d.url : '—';
    document.getElementById('spec-value').textContent = d && d.value != null
      ? d.value + (s.unit ? ' ' + s.unit : '')
      : '—';

    const originalPrompt = history.length > 0 ? history[0].content : (s.description || s.name);
    document.getElementById('f-prompt').value = originalPrompt;
    document.getElementById('f-name').value = s.name;
    document.getElementById('f-description').value = s.description;
    document.getElementById('f-metric-description').value = s.metric_description;
    document.getElementById('f-chart-type').value = s.dashboard_chart_type;
    document.getElementById('f-topic').value = s.topic;
    document.getElementById('f-condition').value = s.condition;
    document.getElementById('f-threshold').value = s.threshold != null ? s.threshold : '';
    document.getElementById('f-unit').value = s.unit || '';
    document.getElementById('f-search-query').value = s.search_query;
    document.getElementById('f-interval').value = s.interval_minutes;
    document.getElementById('f-history').value = JSON.stringify(history);
    document.getElementById('f-source-url').value = d ? (d.url || '') : '';
    document.getElementById('f-source-selector').value = d ? (d.selector || '') : '';
    document.getElementById('f-source-extraction-query').value = d ? (d.extraction_query || '') : '';
    document.getElementById('f-source-verified').value = d && d.success ? 'true' : 'false';
  }

  window.reviseSignal = function() {
    document.getElementById('confirm-phase').classList.add('hidden');
    document.getElementById('discovery-phase').classList.add('hidden');
    document.getElementById('chat-phase').classList.remove('hidden');
    document.getElementById('chat-input').focus();
  };

  // --- Init ---
  document.getElementById('chat-send').addEventListener('click', function() {
    sendMessage(document.getElementById('chat-input').value);
  });
  document.getElementById('chat-input').addEventListener('keydown', function(e) {
    if (e.key === 'Enter') sendMessage(e.target.value);
  });

  appendMessage('agent', 'What do you want to monitor? Describe it in plain English.');
  document.getElementById('chat-input').focus();
})();
</script>
```

**Step 2: Commit**

```bash
git add src/templates/partials/create_modal.html
git commit -m "feat: add Phase 1.5 discovery UI to create modal"
```

---

### Task 7: Smoke test end-to-end

**Step 1: Ensure MongoDB and app are running**

```bash
# Terminal 1 — MongoDB (already running via Docker)
docker compose up -d

# Terminal 2 — App
cd /Users/juanroldan/develop/signals-app
uv run python run_local.py --no-reload
```

**Step 2: Test discovery endpoint directly**

```bash
curl -s -X POST http://127.0.0.1:8000/signals/discover \
  -H "Content-Type: application/json" \
  -d '{"topic": "Bitcoin price", "search_query": "Bitcoin price USD today"}' | python3 -m json.tool
```

Expected: JSON with `success: true`, `url`, `value`, optionally `selector`.

**Step 3: Test full create flow in browser**

Navigate to `http://127.0.0.1:8000/app`, click NEW SIGNAL.

- Type: `alert me when Bitcoin price drops below 45000 USD`
- Expect: agent asks minimal follow-up (or skips straight to done)
- Expect: discovery phase shows `⟳ SCANNING SOURCE...` then `Found: ...` + value
- Type `A` to confirm
- Expect: confirmation card shows SOURCE and VALUE rows
- Click CONFIRM & CREATE

**Step 4: Verify signal stored correctly**

Navigate to the new signal's detail page. Check:
- Description and metric_description appear
- Source URL appears (add to signal_detail.html if missing — see Task 8)

**Step 5: Test RUN NOW**

Click RUN NOW on the signal card. Check that it uses the Playwright path (not DuckDuckGo) — verify in app logs that no DuckDuckGo search is made.

---

### Task 8: Show source_url on signal detail page

**Files:**
- Modify: `src/templates/signal_detail.html`

**Step 1: Add source URL display** in the signal info card, after the `metric_description` block:

Find this block:
```html
      {% if signal.metric_description %}
      <p class="text-gray-700 text-xs font-mono mt-1">METRIC: <span class="text-gray-500">{{ signal.metric_description }}</span></p>
      {% endif %}
```

Add immediately after:
```html
      {% if signal.source_url %}
      <p class="text-gray-700 text-xs font-mono mt-1">SOURCE: <a href="{{ signal.source_url }}" target="_blank" class="text-neon-blue hover:underline">{{ signal.source_url }}</a></p>
      {% endif %}
```

**Step 2: Commit**

```bash
git add src/templates/signal_detail.html
git commit -m "feat: show source_url on signal detail page"
```
