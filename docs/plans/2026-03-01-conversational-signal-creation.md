# Conversational Signal Creation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace one-shot signal creation with an adaptive terminal-style conversational agent that gathers requirements before storing a signal.

**Architecture:** A stateless backend chat endpoint receives conversation history + new message on every turn, calls Gemini, and returns the next agent message. The browser holds the history array in JS. When the agent is satisfied (`done: true`), the modal transitions from chat phase to a confirmation card. Nothing is stored until the user clicks CONFIRM.

**Tech Stack:** FastAPI, HTMX, Jinja2, Beanie/MongoDB, Google Gemini (`google-genai`), Tailwind CSS, vanilla JS (no new deps).

---

### Task 1: Extend the Signal model

**Files:**
- Modify: `src/models/signal.py`

**Step 1: Add new fields to `Signal`**

In `src/models/signal.py`, add these fields to the `Signal` document class after `consecutive_errors`:

```python
from typing import Optional, List

# new fields
description: Optional[str] = None
metric_description: Optional[str] = None
conversation_history: List[dict] = Field(default_factory=list)
dashboard_chart_type: str = "line"  # "line" | "bar" | "gauge"
```

The full updated `Signal` class:

```python
class Signal(Document):
    name: str
    prompt: str
    parsed: ParsedSignal
    interval_minutes: int = 60
    alert_enabled: bool = True
    status: SignalStatus = SignalStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_run_at: Optional[datetime] = None
    last_value: Optional[float] = None
    alert_triggered: bool = False
    consecutive_errors: int = 0
    description: Optional[str] = None
    metric_description: Optional[str] = None
    conversation_history: List[dict] = Field(default_factory=list)
    dashboard_chart_type: str = "line"

    class Settings:
        name = "signals"
```

**Step 2: Verify app still imports cleanly**

```bash
cd /Users/juanroldan/develop/signals-app
uv run python -c "from src.models.signal import Signal; print('OK')"
```

Expected: `OK`

**Step 3: Commit**

```bash
git add src/models/signal.py
git commit -m "feat: add description, metric_description, conversation_history, dashboard_chart_type to Signal"
```

---

### Task 2: Add `run_chat_turn()` to `llm.py`

**Files:**
- Modify: `src/services/llm.py`

**Step 1: Add the `ChatTurnResult` model and system prompt**

Add to `src/services/llm.py` after the existing `UnsupportedPromptError` class:

```python
from pydantic import BaseModel


class SignalSpec(BaseModel):
    name: str
    description: str
    metric_description: str
    dashboard_chart_type: str  # "line" | "bar" | "gauge"
    topic: str
    condition: str
    threshold: Optional[float] = None
    unit: Optional[str] = None
    search_query: str
    interval_minutes: int


class ChatTurnResult(BaseModel):
    message: str
    done: bool
    spec: Optional[SignalSpec] = None


CHAT_SYSTEM_PROMPT = """You are a signal requirements agent for a monitoring app. Your job is to gather requirements for a new signal by asking the user short, focused questions — one at a time.

A signal monitors a metric over time and can trigger alerts. It displays data on a dashboard chart.

You need to determine:
1. What to monitor (topic + best web search query)
2. Alert condition: which operator (>, <, >=, <=, ==, contains) and threshold value — or no alert, just track
3. Unit of the metric (USD, %, count, etc.)
4. Dashboard chart type: "line" for values over time, "bar" for counts/comparisons, "gauge" for 0-100% or ratio metrics
5. Check interval in minutes

Rules:
- Evaluate the user's initial prompt. If it's already precise (topic + condition + threshold + unit all clear), skip straight to done.
- Ask ONE question at a time. Use lettered options [A] [B] [C] when possible.
- Be concise. Terminal style. No fluff.
- When you have everything, respond with a JSON block (and nothing else outside it).

When done, respond ONLY with this JSON (no markdown fences, no explanation):
{
  "done": true,
  "message": "Requirements clear. Generating spec...",
  "spec": {
    "name": "<short title case name>",
    "description": "<1-2 sentence human-readable purpose>",
    "metric_description": "<technical: what metric, unit, operator, threshold, how sourced>",
    "dashboard_chart_type": "line|bar|gauge",
    "topic": "<short topic>",
    "condition": "<>, <, >=, <=, ==, or contains>",
    "threshold": <number or null>,
    "unit": "<unit string or null>",
    "search_query": "<optimal DuckDuckGo search query>",
    "interval_minutes": <number>
  }
}

When NOT done, respond ONLY with this JSON:
{
  "done": false,
  "message": "<your next question or response>"
}
"""
```

**Step 2: Add `run_chat_turn()` function**

Add after the existing `parse_prompt()` function:

```python
async def run_chat_turn(
    history: list[dict],
    message: str,
) -> ChatTurnResult:
    client = genai.Client(api_key=settings.gemini_api_key)

    # Build contents list: system prompt + alternating user/model turns + new user message
    contents = [CHAT_SYSTEM_PROMPT]
    for turn in history:
        contents.append(f"{turn['role'].upper()}: {turn['content']}")
    contents.append(f"USER: {message}")

    response = await client.aio.models.generate_content(
        model="gemini-2.0-flash",
        contents="\n\n".join(contents),
    )

    raw = response.text.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # LLM returned plain text — treat as a chat message, not done
        return ChatTurnResult(done=False, message=raw)

    if data.get("done") and data.get("spec"):
        return ChatTurnResult(
            done=True,
            message=data.get("message", "Requirements clear."),
            spec=SignalSpec(**data["spec"]),
        )

    return ChatTurnResult(
        done=False,
        message=data.get("message", raw),
    )
```

**Step 3: Verify import**

```bash
uv run python -c "from src.services.llm import run_chat_turn, ChatTurnResult, SignalSpec; print('OK')"
```

Expected: `OK`

**Step 4: Commit**

```bash
git add src/services/llm.py
git commit -m "feat: add run_chat_turn, SignalSpec, ChatTurnResult to llm service"
```

---

### Task 3: Add `POST /signals/chat` endpoint

**Files:**
- Modify: `src/routes/signals.py`

**Step 1: Add the chat endpoint**

Add this import at the top of `src/routes/signals.py`:

```python
from pydantic import BaseModel as PydanticBaseModel
```

Add this request body model and endpoint before the existing `create_signal` route:

```python
class ChatRequest(PydanticBaseModel):
    history: list[dict]
    message: str


@router.post("/signals/chat")
async def chat_turn(body: ChatRequest):
    from src.services.llm import run_chat_turn
    from fastapi.responses import JSONResponse
    result = await run_chat_turn(body.history, body.message)
    return JSONResponse(result.model_dump())
```

**Step 2: Verify the route is registered**

```bash
uv run python -c "
from src.routes.signals import router
routes = [r.path for r in router.routes]
print(routes)
assert '/signals/chat' in routes, 'Route missing!'
print('OK')
"
```

Expected: list of routes including `/signals/chat`, then `OK`

**Step 3: Commit**

```bash
git add src/routes/signals.py
git commit -m "feat: add POST /signals/chat endpoint for conversational signal creation"
```

---

### Task 4: Extend `POST /signals` to accept new fields

**Files:**
- Modify: `src/routes/signals.py`

**Step 1: Replace the `create_signal` handler**

Replace the existing `create_signal` function with this version that accepts the new fields from the confirmed spec:

```python
@router.post("/signals", response_class=HTMLResponse)
async def create_signal(
    request: Request,
    prompt: Annotated[str, Form()],
    name: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    metric_description: Annotated[str, Form()] = "",
    dashboard_chart_type: Annotated[str, Form()] = "line",
    topic: Annotated[str, Form()] = "",
    condition: Annotated[str, Form()] = "contains",
    threshold: Annotated[str, Form()] = "",
    unit: Annotated[str, Form()] = "",
    search_query: Annotated[str, Form()] = "",
    interval_minutes: Annotated[int, Form()] = 60,
    conversation_history_json: Annotated[str, Form()] = "[]",
):
    from src.templates_config import templates
    from fastapi.responses import Response
    from src.models.signal import ParsedSignal
    import json as _json

    # Parse conversation history
    try:
        history = _json.loads(conversation_history_json)
    except Exception:
        history = []

    # Parse threshold
    threshold_val: Optional[float] = None
    if threshold:
        try:
            threshold_val = float(threshold)
        except ValueError:
            pass

    parsed = ParsedSignal(
        topic=topic or name,
        condition=condition,
        threshold=threshold_val,
        unit=unit or None,
        search_query=search_query or prompt,
    )

    signal = Signal(
        name=name or parsed.topic.title(),
        prompt=prompt,
        parsed=parsed,
        interval_minutes=interval_minutes,
        description=description or None,
        metric_description=metric_description or None,
        conversation_history=history,
        dashboard_chart_type=dashboard_chart_type,
    )
    await signal.insert()
    schedule_signal(signal)

    if request.headers.get("HX-Request"):
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = "/app"
        return response
    return RedirectResponse(url="/app", status_code=303)
```

**Step 2: Add `Optional` import if not present**

Ensure `from typing import Annotated, Optional` is at the top of `src/routes/signals.py`.

**Step 3: Commit**

```bash
git add src/routes/signals.py
git commit -m "feat: extend POST /signals to accept spec fields from conversational flow"
```

---

### Task 5: Replace `create_modal.html` with two-phase chat modal

**Files:**
- Modify: `src/templates/partials/create_modal.html`

**Step 1: Replace entire file**

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
      <!-- Message log -->
      <div id="chat-log" class="px-6 py-4 space-y-3 min-h-[180px] max-h-72 overflow-y-auto font-mono text-sm">
        <!-- Messages injected by JS -->
      </div>

      <!-- Input row -->
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

    <!-- PHASE 2: Confirmation card (hidden until agent is done) -->
    <div id="confirm-phase" class="hidden px-6 py-5 font-mono">
      <div class="border border-dark-border rounded p-4 space-y-2 text-xs mb-5">
        <div class="text-gray-500 tracking-wider mb-3">SIGNAL SPEC</div>
        <div class="flex gap-3"><span class="text-gray-600 w-24">NAME</span><span id="spec-name" class="text-white"></span></div>
        <div class="flex gap-3"><span class="text-gray-600 w-24">METRIC</span><span id="spec-metric" class="text-gray-300"></span></div>
        <div class="flex gap-3"><span class="text-gray-600 w-24">ALERT</span><span id="spec-alert" class="text-gray-300"></span></div>
        <div class="flex gap-3"><span class="text-gray-600 w-24">DASHBOARD</span><span id="spec-dashboard" class="text-gray-300"></span></div>
        <div class="flex gap-3"><span class="text-gray-600 w-24">INTERVAL</span><span id="spec-interval" class="text-gray-300"></span></div>
      </div>

      <!-- Hidden form submitted on CONFIRM -->
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

        <div class="flex gap-3">
          <button type="button" onclick="reviseSignal()"
            class="flex-1 py-2 border border-dark-border text-gray-500 text-xs font-mono rounded hover:border-gray-500 hover:text-gray-300 transition-all">
            ← REVISE
          </button>
          <button type="submit"
            class="flex-1 py-2 bg-neon-green text-black font-bold text-xs rounded tracking-wider hover:bg-neon-green/90 transition-all">
            CONFIRM & CREATE
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
    msg.className = role === 'agent' ? 'text-gray-300 whitespace-pre-wrap' : 'text-gray-400 whitespace-pre-wrap';
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

    try {
      const res = await fetch('/signals/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ history: history.slice(0, -1), message: text }),
      });
      const data = await res.json();

      appendMessage('agent', data.message);
      history.push({ role: 'agent', content: data.message });

      if (data.done && data.spec) {
        currentSpec = data.spec;
        setTimeout(showConfirmPhase, 600);
      }
    } catch (e) {
      appendMessage('agent', '⚠ Connection error. Please try again.');
    } finally {
      input.disabled = false;
      sendBtn.disabled = false;
      spinner.classList.add('hidden');
      input.value = '';
      input.focus();
    }
  }

  function showConfirmPhase() {
    const s = currentSpec;
    document.getElementById('confirm-phase').classList.remove('hidden');
    document.getElementById('chat-phase').classList.add('hidden');

    document.getElementById('spec-name').textContent = s.name;
    document.getElementById('spec-metric').textContent = s.metric_description;
    const alertText = s.threshold != null
      ? `triggers when ${s.topic} ${s.condition} ${s.threshold}${s.unit ? ' ' + s.unit : ''}`
      : 'dashboard only — no alert';
    document.getElementById('spec-alert').textContent = alertText;
    document.getElementById('spec-dashboard').textContent =
      s.dashboard_chart_type.charAt(0).toUpperCase() + s.dashboard_chart_type.slice(1) + ' chart';
    document.getElementById('spec-interval').textContent = `every ${s.interval_minutes} min`;

    // Populate hidden form fields
    document.getElementById('f-prompt').value = s.description || s.name;
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
  }

  window.reviseSignal = function() {
    document.getElementById('confirm-phase').classList.add('hidden');
    document.getElementById('chat-phase').classList.remove('hidden');
    document.getElementById('chat-input').focus();
  };

  // Wire up send button and Enter key
  document.getElementById('chat-send').addEventListener('click', () => {
    sendMessage(document.getElementById('chat-input').value);
  });
  document.getElementById('chat-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') sendMessage(e.target.value);
  });

  // Kick off: send empty message to get the agent's opening question
  const input = document.getElementById('chat-input');
  const initialPrompt = input.getAttribute('data-initial') || '';
  if (initialPrompt) {
    sendMessage(initialPrompt);
  } else {
    appendMessage('agent', 'What do you want to monitor? Describe it in plain English.');
    input.focus();
  }
})();
</script>
```

**Step 2: Commit**

```bash
git add src/templates/partials/create_modal.html
git commit -m "feat: replace create modal with two-phase conversational terminal UI"
```

---

### Task 6: Add description + creation history to signal detail page

**Files:**
- Modify: `src/templates/signal_detail.html`

**Step 1: Add description and metric_description to the info panel**

In `signal_detail.html`, inside the first `<div class="p-5 rounded-lg border border-dark-border bg-dark-card">` block (the signal info card), add after the condition line (after line 34):

```html
{% if signal.description %}
<p class="text-gray-500 text-xs font-mono mt-3 leading-relaxed">{{ signal.description }}</p>
{% endif %}
{% if signal.metric_description %}
<p class="text-gray-700 text-xs font-mono mt-1">METRIC: <span class="text-gray-500">{{ signal.metric_description }}</span></p>
{% endif %}
```

**Step 2: Add collapsed "Creation History" section**

Add a new panel inside the left column (`lg:col-span-1 space-y-4`), after the ALERTS panel:

```html
{% if signal.conversation_history %}
<div class="p-5 rounded-lg border border-dark-border bg-dark-card">
  <button onclick="this.nextElementSibling.classList.toggle('hidden')"
    class="w-full flex items-center justify-between text-xs font-mono text-gray-500 tracking-wider hover:text-gray-400 transition-colors">
    <span>CREATION HISTORY</span>
    <span class="text-gray-700">▾</span>
  </button>
  <div class="hidden mt-4 space-y-2 max-h-64 overflow-y-auto">
    {% for turn in signal.conversation_history %}
    <div class="flex gap-2 text-xs font-mono">
      <span class="{% if turn.role == 'agent' %}text-neon-green{% else %}text-gray-600{% endif %} shrink-0 font-bold">
        {% if turn.role == 'agent' %}[AGENT]{% else %}[YOU]{% endif %}
      </span>
      <span class="text-gray-500 whitespace-pre-wrap">{{ turn.content }}</span>
    </div>
    {% endfor %}
  </div>
</div>
{% endif %}
```

**Step 3: Commit**

```bash
git add src/templates/signal_detail.html
git commit -m "feat: show description, metric_description, and creation history on signal detail page"
```

---

### Task 7: Smoke test the full flow

**Step 1: Start the app**

```bash
uv run python run_local.py --no-reload
```

**Step 2: Open the dashboard and create a new signal**

Navigate to `http://127.0.0.1:8000/app`, click NEW SIGNAL.

**Test A — Vague prompt:**
Type `monitor Tesla`. Expect: agent asks follow-up questions (condition, threshold, interval). After answering, spec card appears. Clicking CONFIRM creates signal and redirects to `/app`.

**Test B — Precise prompt:**
Type `alert me when Bitcoin price drops below 45000 USD`. Expect: agent skips straight to confirmation card with pre-filled spec.

**Step 3: Check signal detail page**

Click VIEW on the new signal. Confirm:
- `description` text appears under the signal name
- `metric_description` appears below it
- "CREATION HISTORY" section is present and expands on click showing the full conversation

**Step 4: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: address issues found during smoke test"
```
