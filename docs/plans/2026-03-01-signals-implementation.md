# Signals App Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a FastAPI + Jinja2 personal alert and dashboard app where users write natural-language prompts to monitor anything, powered by Gemini Flash and DuckDuckGo.

**Architecture:** LLM parses a prompt once at creation time into structured config (topic, condition, threshold, search_query). APScheduler runs each signal's executor on a configurable interval (default 1 hr). Results stored in MongoDB, rendered via Jinja2 with HTMX for partial updates.

**Tech Stack:** Python 3.14, uv, FastAPI, Jinja2, Beanie (MongoDB ODM), Motor (async MongoDB driver), Gemini Flash (`google-generativeai`), `duckduckgo-search`, APScheduler, Tailwind CSS (CDN), Chart.js (CDN), HTMX (CDN), pytest + pytest-asyncio + httpx

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/__init__.py`
- Create: `src/main.py`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `tests/__init__.py`

**Step 1: Initialize uv project**

```bash
cd /Users/juanroldan/develop/signals-app
uv init --python 3.14 --no-workspace
```

Expected: `pyproject.toml` created with Python 3.14 requirement.

**Step 2: Add dependencies**

```bash
uv add fastapi uvicorn[standard] jinja2 python-multipart \
       beanie motor \
       google-generativeai \
       duckduckgo-search \
       apscheduler \
       pydantic-settings \
       python-dotenv

uv add --dev pytest pytest-asyncio httpx mongomock-motor
```

**Step 3: Create directory structure**

```bash
mkdir -p src/routes src/services src/models src/templates/partials tests
touch src/__init__.py src/routes/__init__.py src/services/__init__.py src/models/__init__.py
touch tests/__init__.py
```

**Step 4: Create `.env.example`**

```
GEMINI_API_KEY=your_key_here
MONGO_URI=mongodb://localhost:27017
MONGO_DB=signals
DEFAULT_INTERVAL_MINUTES=60
```

**Step 5: Create `.gitignore`**

```
.env
__pycache__/
*.pyc
.venv/
*.egg-info/
.pytest_cache/
```

**Step 6: Create minimal `src/main.py` that starts**

```python
from fastapi import FastAPI

app = FastAPI(title="Signals")

@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Step 7: Run and verify**

```bash
uv run uvicorn src.main:app --reload
```

Expected: `GET http://localhost:8000/health` returns `{"status": "ok"}`.

**Step 8: Commit**

```bash
git add .
git commit -m "feat: scaffold FastAPI project with uv and Python 3.14"
```

---

## Task 2: Configuration

**Files:**
- Create: `src/config.py`
- Create: `tests/test_config.py`

**Step 1: Write the failing test**

```python
# tests/test_config.py
from src.config import Settings

def test_settings_defaults():
    s = Settings(
        gemini_api_key="test-key",
        mongo_uri="mongodb://localhost:27017",
    )
    assert s.default_interval_minutes == 60
    assert s.mongo_db == "signals"
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_config.py -v
```

Expected: FAIL with `ImportError: cannot import name 'Settings'`

**Step 3: Implement `src/config.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    gemini_api_key: str
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "signals"
    default_interval_minutes: int = 60


settings = Settings()
```

**Step 4: Run test to verify it passes**

```bash
uv run pytest tests/test_config.py -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: add pydantic-settings configuration"
```

---

## Task 3: MongoDB Models

**Files:**
- Create: `src/models/signal.py`
- Create: `src/models/signal_run.py`
- Create: `tests/test_models.py`

**Step 1: Write the failing test**

```python
# tests/test_models.py
from datetime import datetime, timezone
from src.models.signal import Signal, ParsedSignal, SignalStatus
from src.models.signal_run import SignalRun, RunStatus


def test_signal_defaults():
    parsed = ParsedSignal(
        topic="gold price",
        condition=">",
        threshold=30.0,
        unit="USD",
        search_query="current gold price USD",
    )
    signal = Signal(
        name="Gold Alert",
        prompt="Alert when gold > 30 USD",
        parsed=parsed,
    )
    assert signal.status == SignalStatus.ACTIVE
    assert signal.alert_enabled is True
    assert signal.interval_minutes == 60
    assert signal.consecutive_errors == 0


def test_signal_run_defaults():
    run = SignalRun(
        signal_id="fake_id",
        value=28.5,
        alert_triggered=False,
        raw_result="Gold is at $28.50",
    )
    assert run.status == RunStatus.OK
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_models.py -v
```

Expected: FAIL with `ImportError`

**Step 3: Implement `src/models/signal.py`**

```python
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from beanie import Document
from pydantic import BaseModel, Field


class SignalStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    ERROR = "error"


class ParsedSignal(BaseModel):
    topic: str
    condition: str  # ">", "<", ">=", "<=", "==", "contains"
    threshold: Optional[float] = None
    unit: Optional[str] = None
    search_query: str


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

    class Settings:
        name = "signals"
```

**Step 4: Implement `src/models/signal_run.py`**

```python
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from beanie import Document
from pydantic import Field


class RunStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    TRIGGERED = "triggered"


class SignalRun(Document):
    signal_id: str
    ran_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    value: Optional[float] = None
    alert_triggered: bool = False
    status: RunStatus = RunStatus.OK
    raw_result: str = ""

    class Settings:
        name = "signal_runs"
```

**Step 5: Run test to verify it passes**

```bash
uv run pytest tests/test_models.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add src/models/ tests/test_models.py
git commit -m "feat: add Signal and SignalRun Beanie document models"
```

---

## Task 4: Database Initialization

**Files:**
- Create: `src/db.py`
- Modify: `src/main.py`

**Step 1: Create `src/db.py`**

```python
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from src.config import settings
from src.models.signal import Signal
from src.models.signal_run import SignalRun


async def init_db():
    client = AsyncIOMotorClient(settings.mongo_uri)
    await init_beanie(
        database=client[settings.mongo_db],
        document_models=[Signal, SignalRun],
    )
```

**Step 2: Update `src/main.py` with lifespan**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(title="Signals", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Step 3: Commit**

```bash
git add src/db.py src/main.py
git commit -m "feat: add MongoDB init with Beanie in FastAPI lifespan"
```

---

## Task 5: LLM Service (Gemini Flash prompt parser)

**Files:**
- Create: `src/services/llm.py`
- Create: `tests/test_llm.py`

**Step 1: Write the failing test**

```python
# tests/test_llm.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.services.llm import parse_prompt, UnsupportedPromptError


@pytest.mark.asyncio
async def test_parse_prompt_returns_parsed_signal():
    mock_response_text = '{"supported": true, "topic": "gold price", "condition": ">", "threshold": 30.0, "unit": "USD", "search_query": "current gold price USD today"}'

    with patch("src.services.llm.genai") as mock_genai:
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content_async = AsyncMock(
            return_value=MagicMock(text=mock_response_text)
        )

        result = await parse_prompt("Alert when gold > 30 USD")

    assert result.topic == "gold price"
    assert result.condition == ">"
    assert result.threshold == 30.0


@pytest.mark.asyncio
async def test_parse_prompt_raises_on_unsupported():
    mock_response_text = '{"supported": false, "reason": "Cannot determine data source"}'

    with patch("src.services.llm.genai") as mock_genai:
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content_async = AsyncMock(
            return_value=MagicMock(text=mock_response_text)
        )

        with pytest.raises(UnsupportedPromptError) as exc_info:
            await parse_prompt("What is the meaning of life?")

    assert "Cannot determine data source" in str(exc_info.value)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_llm.py -v
```

Expected: FAIL with `ImportError`

**Step 3: Implement `src/services/llm.py`**

```python
import json
import re
import google.generativeai as genai
from src.config import settings
from src.models.signal import ParsedSignal

SYSTEM_PROMPT = """You are a signal parser. Given a user's monitoring prompt, extract structured data.

Return ONLY valid JSON (no markdown, no explanation):

If the prompt describes something you can monitor via a web search:
{
  "supported": true,
  "topic": "<short topic name>",
  "condition": "<one of: >, <, >=, <=, ==, contains>",
  "threshold": <number or null>,
  "unit": "<unit string or null>",
  "search_query": "<optimal DuckDuckGo search query to find current value>"
}

If not monitorable:
{
  "supported": false,
  "reason": "<short explanation>"
}
"""


class UnsupportedPromptError(Exception):
    pass


async def parse_prompt(prompt: str) -> ParsedSignal:
    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")
    response = await model.generate_content_async(f"{SYSTEM_PROMPT}\n\nUser prompt: {prompt}")

    raw = response.text.strip()
    # Strip markdown code fences if present
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()

    data = json.loads(raw)

    if not data.get("supported"):
        raise UnsupportedPromptError(data.get("reason", "Prompt not supported"))

    return ParsedSignal(
        topic=data["topic"],
        condition=data["condition"],
        threshold=data.get("threshold"),
        unit=data.get("unit"),
        search_query=data["search_query"],
    )
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_llm.py -v
```

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/services/llm.py tests/test_llm.py
git commit -m "feat: add Gemini Flash LLM service for prompt parsing"
```

---

## Task 6: Search Service (DuckDuckGo)

**Files:**
- Create: `src/services/search.py`
- Create: `tests/test_search.py`

**Step 1: Write the failing test**

```python
# tests/test_search.py
import pytest
from unittest.mock import patch, MagicMock
from src.services.search import search_web


@pytest.mark.asyncio
async def test_search_web_returns_text():
    mock_results = [
        {"title": "Gold Price Today", "body": "Gold is trading at $62 per gram.", "href": "https://example.com"},
    ]
    with patch("src.services.search.DDGS") as mock_ddgs:
        instance = MagicMock()
        mock_ddgs.return_value.__enter__ = MagicMock(return_value=instance)
        mock_ddgs.return_value.__exit__ = MagicMock(return_value=False)
        instance.text.return_value = mock_results

        result = await search_web("current gold price per gram USD")

    assert "Gold is trading" in result
    assert len(result) > 0


@pytest.mark.asyncio
async def test_search_web_returns_empty_string_on_no_results():
    with patch("src.services.search.DDGS") as mock_ddgs:
        instance = MagicMock()
        mock_ddgs.return_value.__enter__ = MagicMock(return_value=instance)
        mock_ddgs.return_value.__exit__ = MagicMock(return_value=False)
        instance.text.return_value = []

        result = await search_web("xyzzy frobble 12345")

    assert result == ""
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_search.py -v
```

Expected: FAIL with `ImportError`

**Step 3: Implement `src/services/search.py`**

```python
import asyncio
from duckduckgo_search import DDGS


async def search_web(query: str, max_results: int = 5) -> str:
    """Run a DuckDuckGo search and return concatenated snippet text."""
    loop = asyncio.get_event_loop()

    def _search():
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
        return results

    results = await loop.run_in_executor(None, _search)

    if not results:
        return ""

    return "\n\n".join(
        f"{r.get('title', '')}: {r.get('body', '')}" for r in results
    )
```

**Step 4: Run tests**

```bash
uv run pytest tests/test_search.py -v
```

Expected: PASS (2 tests)

**Step 5: Commit**

```bash
git add src/services/search.py tests/test_search.py
git commit -m "feat: add DuckDuckGo search service"
```

---

## Task 7: Executor Service (signal check runner)

**Files:**
- Create: `src/services/executor.py`
- Create: `tests/test_executor.py`

**Step 1: Write the failing tests**

```python
# tests/test_executor.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from src.services.executor import evaluate_condition, extract_value_from_text


def test_evaluate_condition_greater_than():
    assert evaluate_condition(35.0, ">", 30.0) is True
    assert evaluate_condition(25.0, ">", 30.0) is False


def test_evaluate_condition_less_than():
    assert evaluate_condition(25.0, "<", 30.0) is True
    assert evaluate_condition(35.0, "<", 30.0) is False


def test_evaluate_condition_contains():
    # contains checks are text-based, threshold is None
    assert evaluate_condition(None, "contains", None, text="Bitcoin surges past record") is True


@pytest.mark.asyncio
async def test_extract_value_from_text():
    mock_response_text = "62.50"
    with patch("src.services.executor.genai") as mock_genai:
        mock_model = MagicMock()
        mock_genai.GenerativeModel.return_value = mock_model
        mock_model.generate_content_async = AsyncMock(
            return_value=MagicMock(text=mock_response_text)
        )
        value = await extract_value_from_text("gold price", "Gold is $62.50 per gram today")
    assert value == 62.50
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_executor.py -v
```

Expected: FAIL with `ImportError`

**Step 3: Implement `src/services/executor.py`**

```python
import re
from typing import Optional
import google.generativeai as genai
from src.config import settings


def evaluate_condition(
    value: Optional[float],
    condition: str,
    threshold: Optional[float],
    text: str = "",
) -> bool:
    if condition == "contains":
        return text.lower() != ""
    if value is None or threshold is None:
        return False
    ops = {
        ">": value > threshold,
        "<": value < threshold,
        ">=": value >= threshold,
        "<=": value <= threshold,
        "==": value == threshold,
    }
    return ops.get(condition, False)


async def extract_value_from_text(topic: str, text: str) -> Optional[float]:
    """Ask Gemini to extract a numeric value for the topic from search results."""
    genai.configure(api_key=settings.gemini_api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = (
        f"Extract the current numeric value for '{topic}' from the text below.\n"
        f"Return ONLY the number (e.g. 62.50), no units, no text, no explanation.\n"
        f"If you cannot find a clear numeric value, return null.\n\n"
        f"Text:\n{text[:3000]}"
    )

    response = await model.generate_content_async(prompt)
    raw = response.text.strip()

    if raw.lower() in ("null", "none", ""):
        return None

    match = re.search(r"[\d,]+\.?\d*", raw.replace(",", ""))
    if match:
        try:
            return float(match.group().replace(",", ""))
        except ValueError:
            return None
    return None


async def run_signal(signal) -> dict:
    """
    Run one check cycle for a signal.
    Returns dict with: value, alert_triggered, raw_result, status
    """
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
        triggered = signal.parsed.topic.lower() in raw_result.lower()
        return {
            "value": None,
            "alert_triggered": triggered,
            "raw_result": raw_result,
            "status": "ok",
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

**Step 4: Run tests**

```bash
uv run pytest tests/test_executor.py -v
```

Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add src/services/executor.py tests/test_executor.py
git commit -m "feat: add executor service for signal condition evaluation"
```

---

## Task 8: Scheduler Service

**Files:**
- Create: `src/services/scheduler.py`
- Modify: `src/main.py` (add scheduler to lifespan)

**Step 1: Create `src/services/scheduler.py`**

```python
from datetime import datetime, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = AsyncIOScheduler()


async def _run_signal_job(signal_id: str):
    from src.models.signal import Signal, SignalStatus
    from src.models.signal_run import SignalRun, RunStatus
    from src.services.executor import run_signal

    signal = await Signal.get(signal_id)
    if not signal or signal.status == SignalStatus.PAUSED:
        return

    result = await run_signal(signal)

    run = SignalRun(
        signal_id=signal_id,
        value=result["value"],
        alert_triggered=result["alert_triggered"],
        raw_result=result["raw_result"],
        status=result["status"],
    )
    await run.insert()

    signal.last_run_at = datetime.now(timezone.utc)
    signal.last_value = result["value"]
    signal.alert_triggered = result["alert_triggered"]

    if result["status"] == "error":
        signal.consecutive_errors += 1
        if signal.consecutive_errors >= 5:
            signal.status = SignalStatus.PAUSED
    else:
        signal.consecutive_errors = 0
        signal.status = SignalStatus.ACTIVE

    await signal.save()


def schedule_signal(signal):
    signal_id = str(signal.id)
    job_id = f"signal_{signal_id}"

    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)

    scheduler.add_job(
        _run_signal_job,
        trigger=IntervalTrigger(minutes=signal.interval_minutes),
        id=job_id,
        args=[signal_id],
        replace_existing=True,
    )


def unschedule_signal(signal_id: str):
    job_id = f"signal_{signal_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)


async def load_all_signals():
    """Called at startup to re-schedule all active signals from DB."""
    from src.models.signal import Signal, SignalStatus
    signals = await Signal.find(Signal.status == SignalStatus.ACTIVE).to_list()
    for signal in signals:
        schedule_signal(signal)
```

**Step 2: Update `src/main.py` lifespan to start scheduler**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from src.db import init_db
from src.services.scheduler import scheduler, load_all_signals


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler.start()
    await load_all_signals()
    yield
    scheduler.shutdown()


app = FastAPI(title="Signals", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Step 3: Commit**

```bash
git add src/services/scheduler.py src/main.py
git commit -m "feat: add APScheduler service and wire into app lifespan"
```

---

## Task 9: Signal Routes (API)

**Files:**
- Create: `src/routes/signals.py`
- Create: `tests/test_routes_signals.py`
- Modify: `src/main.py` (include router)

**Step 1: Write the failing test**

```python
# tests/test_routes_signals.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport
from src.main import app


@pytest.mark.asyncio
async def test_create_signal_unsupported_prompt():
    mock_error_msg = "Cannot determine a monitorable condition"
    with patch("src.routes.signals.parse_prompt", side_effect=Exception(mock_error_msg)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/signals",
                data={"prompt": "What is the meaning of life?"},
            )
    assert response.status_code == 200
    assert mock_error_msg in response.text or response.status_code in (200, 422)
```

**Step 2: Run test to verify it fails**

```bash
uv run pytest tests/test_routes_signals.py -v
```

Expected: FAIL

**Step 3: Create `src/routes/signals.py`**

```python
from datetime import timezone, datetime
from typing import Annotated
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from src.models.signal import Signal, SignalStatus
from src.models.signal_run import SignalRun
from src.services.llm import parse_prompt, UnsupportedPromptError
from src.services.scheduler import schedule_signal, unschedule_signal
from src.config import settings

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")


@router.post("/signals", response_class=HTMLResponse)
async def create_signal(request: Request, prompt: Annotated[str, Form()]):
    error = None
    try:
        parsed = await parse_prompt(prompt)
    except (UnsupportedPromptError, Exception) as e:
        error = str(e)
        return templates.TemplateResponse(
            "partials/create_modal.html",
            {"request": request, "error": error, "prompt": prompt},
        )

    signal = Signal(
        name=parsed.topic.title(),
        prompt=prompt,
        parsed=parsed,
        interval_minutes=settings.default_interval_minutes,
    )
    await signal.insert()
    schedule_signal(signal)
    return RedirectResponse(url="/app", status_code=303)


@router.post("/signals/{signal_id}/delete")
async def delete_signal(signal_id: str):
    signal = await Signal.get(signal_id)
    if signal:
        unschedule_signal(signal_id)
        await signal.delete()
    return RedirectResponse(url="/app", status_code=303)


@router.post("/signals/{signal_id}/toggle-alert", response_class=HTMLResponse)
async def toggle_alert(request: Request, signal_id: str):
    signal = await Signal.get(signal_id)
    if signal:
        signal.alert_enabled = not signal.alert_enabled
        await signal.save()
    return templates.TemplateResponse(
        "partials/signal_card.html",
        {"request": request, "signal": signal},
    )


@router.post("/signals/{signal_id}/run-now", response_class=HTMLResponse)
async def run_now(request: Request, signal_id: str):
    from src.services.scheduler import _run_signal_job
    import asyncio
    asyncio.create_task(_run_signal_job(signal_id))
    signal = await Signal.get(signal_id)
    return templates.TemplateResponse(
        "partials/signal_card.html",
        {"request": request, "signal": signal, "running": True},
    )


@router.post("/signals/{signal_id}/update", response_class=HTMLResponse)
async def update_signal(
    request: Request,
    signal_id: str,
    prompt: Annotated[str, Form()],
    interval_minutes: Annotated[int, Form()] = 60,
):
    signal = await Signal.get(signal_id)
    if not signal:
        return RedirectResponse(url="/app", status_code=303)

    error = None
    try:
        parsed = await parse_prompt(prompt)
        signal.prompt = prompt
        signal.parsed = parsed
        signal.name = parsed.topic.title()
    except Exception as e:
        error = str(e)

    signal.interval_minutes = interval_minutes
    signal.consecutive_errors = 0
    signal.status = SignalStatus.ACTIVE
    await signal.save()
    schedule_signal(signal)

    runs = await SignalRun.find(SignalRun.signal_id == signal_id).sort("-ran_at").limit(20).to_list()
    return templates.TemplateResponse(
        "signal_detail.html",
        {"request": request, "signal": signal, "runs": runs, "error": error},
    )
```

**Step 4: Add router to `src/main.py`**

Add after the imports and before the health route:

```python
from src.routes import signals as signals_router
# ...
app.include_router(signals_router.router)
```

**Step 5: Run tests**

```bash
uv run pytest tests/test_routes_signals.py -v
```

Expected: PASS

**Step 6: Commit**

```bash
git add src/routes/signals.py tests/test_routes_signals.py src/main.py
git commit -m "feat: add signal CRUD routes (create, delete, toggle, run-now, update)"
```

---

## Task 10: Landing & Dashboard Routes

**Files:**
- Create: `src/routes/landing.py`
- Create: `src/routes/dashboard.py`
- Modify: `src/main.py`

**Step 1: Create `src/routes/landing.py`**

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")


@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})
```

**Step 2: Create `src/routes/dashboard.py`**

```python
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from src.models.signal import Signal
from src.models.signal_run import SignalRun

router = APIRouter()
templates = Jinja2Templates(directory="src/templates")


@router.get("/app", response_class=HTMLResponse)
async def dashboard(request: Request):
    signals = await Signal.find_all().sort("-created_at").to_list()
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, "signals": signals}
    )


@router.get("/app/signals/{signal_id}", response_class=HTMLResponse)
async def signal_detail(request: Request, signal_id: str):
    signal = await Signal.get(signal_id)
    runs = await SignalRun.find(
        SignalRun.signal_id == signal_id
    ).sort("-ran_at").limit(50).to_list()
    return templates.TemplateResponse(
        "signal_detail.html",
        {"request": request, "signal": signal, "runs": runs},
    )
```

**Step 3: Update `src/main.py` to include all routers**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from src.db import init_db
from src.services.scheduler import scheduler, load_all_signals
from src.routes import landing, dashboard
from src.routes import signals as signals_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler.start()
    await load_all_signals()
    yield
    scheduler.shutdown()


app = FastAPI(title="Signals", lifespan=lifespan)

app.include_router(landing.router)
app.include_router(dashboard.router)
app.include_router(signals_router.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Step 4: Commit**

```bash
git add src/routes/landing.py src/routes/dashboard.py src/main.py
git commit -m "feat: add landing and dashboard routes"
```

---

## Task 11: Base HTML Template (Dark Techy Layout)

**Files:**
- Create: `src/templates/base.html`

**Step 1: Create `src/templates/base.html`**

```html
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{% block title %}Signals{% endblock %}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      darkMode: 'class',
      theme: {
        extend: {
          colors: {
            'neon-green': '#00ff88',
            'neon-blue': '#00cfff',
            'neon-purple': '#a855f7',
            'dark-bg': '#0a0a0f',
            'dark-card': '#12121a',
            'dark-border': '#1e1e2e',
          },
          fontFamily: {
            mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
          }
        }
      }
    }
  </script>
  <script src="https://unpkg.com/htmx.org@1.9.10"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'JetBrains Mono', monospace; }
    .glow-green { box-shadow: 0 0 20px rgba(0, 255, 136, 0.15); }
    .glow-blue  { box-shadow: 0 0 20px rgba(0, 207, 255, 0.15); }
    .glow-red   { box-shadow: 0 0 20px rgba(255, 50, 50, 0.2); }
    .border-glow-green { border-color: #00ff88; box-shadow: 0 0 8px rgba(0,255,136,0.3); }
    .border-glow-red   { border-color: #ff4444; box-shadow: 0 0 8px rgba(255,68,68,0.3); }
    .pulse-dot::before {
      content: '';
      display: inline-block;
      width: 8px; height: 8px;
      border-radius: 50%;
      background: currentColor;
      animation: pulse 2s infinite;
      margin-right: 6px;
    }
    @keyframes pulse {
      0%, 100% { opacity: 1; }
      50% { opacity: 0.3; }
    }
    .scanline {
      background: repeating-linear-gradient(
        0deg,
        transparent,
        transparent 2px,
        rgba(0,0,0,0.03) 2px,
        rgba(0,0,0,0.03) 4px
      );
      pointer-events: none;
    }
  </style>
  {% block head %}{% endblock %}
</head>
<body class="bg-dark-bg text-gray-200 min-h-screen">

  <!-- Nav -->
  <nav class="border-b border-dark-border bg-dark-card/80 backdrop-blur-sm sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
      <a href="/" class="flex items-center gap-2 text-neon-green font-bold text-lg tracking-wider">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>
        </svg>
        SIGNALS
      </a>
      <div class="flex items-center gap-4">
        <a href="/app" class="text-sm text-gray-400 hover:text-neon-green transition-colors">Dashboard</a>
        <span class="text-dark-border">|</span>
        <span class="text-xs text-gray-600">v1.0</span>
      </div>
    </div>
  </nav>

  <!-- Main -->
  <main class="max-w-7xl mx-auto px-4 py-8">
    {% block content %}{% endblock %}
  </main>

  {% block scripts %}{% endblock %}
</body>
</html>
```

**Step 2: Commit**

```bash
git add src/templates/base.html
git commit -m "feat: add dark techy base HTML template"
```

---

## Task 12: Landing Page Template

**Files:**
- Create: `src/templates/landing.html`

**Step 1: Create `src/templates/landing.html`**

```html
{% extends "base.html" %}
{% block title %}Signals — Monitor Anything{% endblock %}
{% block content %}

<!-- Hero -->
<section class="text-center py-24 relative">
  <div class="absolute inset-0 scanline pointer-events-none"></div>

  <!-- Animated grid background -->
  <div class="absolute inset-0 opacity-5" style="background-image: linear-gradient(#00ff88 1px, transparent 1px), linear-gradient(90deg, #00ff88 1px, transparent 1px); background-size: 40px 40px;"></div>

  <div class="relative z-10">
    <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full border border-neon-green/30 text-neon-green text-xs mb-8 bg-neon-green/5">
      <span class="pulse-dot text-neon-green"></span>
      LIVE MONITORING ACTIVE
    </div>

    <h1 class="text-6xl font-bold mb-4 tracking-tight">
      <span class="text-white">Monitor</span>
      <span class="text-neon-green"> anything.</span>
    </h1>
    <h2 class="text-6xl font-bold mb-8 tracking-tight">
      <span class="text-white">Get alerted</span>
      <span class="text-neon-blue"> instantly.</span>
    </h2>

    <p class="text-gray-400 text-lg max-w-xl mx-auto mb-12 leading-relaxed">
      Write a prompt in plain English. Signals watches it for you —
      prices, news, weather, anything — and alerts you the moment conditions are met.
    </p>

    <!-- Demo prompt examples -->
    <div class="flex flex-wrap justify-center gap-3 mb-12">
      {% for example in [
        '"Alert when Bitcoin > $100k"',
        '"Notify me if it rains in Madrid"',
        '"Watch for Apple earnings news"',
        '"Alert when EUR/USD < 1.05"'
      ] %}
      <span class="px-3 py-1.5 rounded border border-dark-border text-gray-500 text-xs font-mono bg-dark-card">
        {{ example }}
      </span>
      {% endfor %}
    </div>

    <a href="/app" class="inline-flex items-center gap-2 px-8 py-4 bg-neon-green text-black font-bold rounded text-sm tracking-wider hover:bg-neon-green/90 transition-all glow-green">
      OPEN DASHBOARD
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 7l5 5m0 0l-5 5m5-5H6"/>
      </svg>
    </a>
  </div>
</section>

<!-- Features -->
<section class="py-16 border-t border-dark-border">
  <div class="grid grid-cols-1 md:grid-cols-3 gap-6">
    {% for feature in [
      {
        "icon": "M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z",
        "title": "Natural Language",
        "desc": "Just describe what you want to monitor. No code, no config files, no APIs to learn."
      },
      {
        "icon": "M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z",
        "title": "Live Dashboard",
        "desc": "Visual charts of historical values, alert status badges, and full run history per signal."
      },
      {
        "icon": "M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9",
        "title": "Smart Alerts",
        "desc": "Enable or disable alerts per signal. Get notified the moment a condition is triggered."
      }
    ] %}
    <div class="p-6 rounded-lg border border-dark-border bg-dark-card hover:border-neon-green/30 transition-all group">
      <div class="w-10 h-10 rounded border border-neon-green/20 bg-neon-green/5 flex items-center justify-center mb-4 group-hover:bg-neon-green/10 transition-all">
        <svg class="w-5 h-5 text-neon-green" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="{{ feature.icon }}"/>
        </svg>
      </div>
      <h3 class="font-bold text-white mb-2 text-sm tracking-wider">{{ feature.title | upper }}</h3>
      <p class="text-gray-500 text-sm leading-relaxed">{{ feature.desc }}</p>
    </div>
    {% endfor %}
  </div>
</section>

{% endblock %}
```

**Step 2: Commit**

```bash
git add src/templates/landing.html
git commit -m "feat: add dark techy landing page template"
```

---

## Task 13: Signal Card Partial & Dashboard Template

**Files:**
- Create: `src/templates/partials/signal_card.html`
- Create: `src/templates/partials/create_modal.html`
- Create: `src/templates/dashboard.html`

**Step 1: Create `src/templates/partials/signal_card.html`**

```html
{% set status_color = {
  'active': 'neon-green',
  'paused': 'yellow-400',
  'error': 'red-400'
} %}
{% set alert_color = 'red-400' if signal.alert_triggered else 'gray-600' %}

<div id="signal-{{ signal.id }}"
     class="p-5 rounded-lg border bg-dark-card transition-all hover:border-neon-green/20
            {% if signal.alert_triggered %}border-glow-red{% else %}border-dark-border{% endif %}">

  <!-- Header -->
  <div class="flex items-start justify-between mb-3">
    <div>
      <div class="flex items-center gap-2 mb-1">
        <span class="text-xs font-mono text-{{ status_color.get(signal.status, 'gray-400') }} pulse-dot">
          {{ signal.status | upper }}
        </span>
        {% if signal.alert_triggered %}
        <span class="text-xs px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20 font-mono">
          ALERT
        </span>
        {% endif %}
      </div>
      <h3 class="font-bold text-white text-sm">{{ signal.name }}</h3>
    </div>
    <a href="/app/signals/{{ signal.id }}" class="text-gray-600 hover:text-neon-blue transition-colors text-xs">
      VIEW →
    </a>
  </div>

  <!-- Prompt snippet -->
  <p class="text-gray-500 text-xs font-mono mb-4 leading-relaxed border-l-2 border-dark-border pl-3">
    {{ signal.prompt[:80] }}{% if signal.prompt | length > 80 %}...{% endif %}
  </p>

  <!-- Current value -->
  <div class="flex items-end gap-1 mb-4">
    {% if signal.last_value is not none %}
    <span class="text-2xl font-bold text-neon-blue">{{ "%.2f"|format(signal.last_value) }}</span>
    {% if signal.parsed.unit %}
    <span class="text-gray-500 text-xs mb-1">{{ signal.parsed.unit }}</span>
    {% endif %}
    {% else %}
    <span class="text-gray-600 text-sm font-mono">— no data yet —</span>
    {% endif %}
  </div>

  <!-- Meta -->
  <div class="flex items-center justify-between text-xs text-gray-600 font-mono mb-4">
    <span>
      {% if signal.last_run_at %}
        checked {{ signal.last_run_at.strftime('%H:%M') }}
      {% else %}
        not run yet
      {% endif %}
    </span>
    <span>every {{ signal.interval_minutes }}m</span>
  </div>

  <!-- Actions -->
  <div class="flex items-center gap-2 border-t border-dark-border pt-3">
    <!-- Alert toggle -->
    <button
      hx-post="/signals/{{ signal.id }}/toggle-alert"
      hx-target="#signal-{{ signal.id }}"
      hx-swap="outerHTML"
      class="flex items-center gap-1.5 px-2 py-1 rounded text-xs font-mono transition-all
             {% if signal.alert_enabled %}text-neon-green bg-neon-green/5 border border-neon-green/20 hover:bg-neon-green/10{% else %}text-gray-600 border border-dark-border hover:border-gray-500{% endif %}">
      <svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9"/>
      </svg>
      {% if signal.alert_enabled %}ALERTS ON{% else %}ALERTS OFF{% endif %}
    </button>

    <!-- Run now -->
    <button
      hx-post="/signals/{{ signal.id }}/run-now"
      hx-target="#signal-{{ signal.id }}"
      hx-swap="outerHTML"
      class="px-2 py-1 rounded text-xs font-mono text-gray-500 border border-dark-border hover:border-neon-blue/30 hover:text-neon-blue transition-all">
      RUN NOW
    </button>

    <!-- Delete -->
    <form method="POST" action="/signals/{{ signal.id }}/delete" class="ml-auto"
          onsubmit="return confirm('Delete this signal?')">
      <button type="submit"
        class="px-2 py-1 rounded text-xs font-mono text-gray-700 border border-dark-border hover:border-red-500/30 hover:text-red-400 transition-all">
        DEL
      </button>
    </form>
  </div>
</div>
```

**Step 2: Create `src/templates/partials/create_modal.html`**

```html
<div id="create-modal"
     class="fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50"
     onclick="if(event.target===this) this.remove()">
  <div class="bg-dark-card border border-dark-border rounded-lg p-6 w-full max-w-lg mx-4" onclick="event.stopPropagation()">
    <div class="flex items-center justify-between mb-6">
      <h2 class="font-bold text-white tracking-wider">NEW SIGNAL</h2>
      <button onclick="document.getElementById('create-modal').remove()"
        class="text-gray-600 hover:text-white transition-colors text-xl">×</button>
    </div>

    <form method="POST" action="/signals"
          hx-post="/signals"
          hx-target="#create-modal"
          hx-swap="outerHTML"
          hx-indicator="#create-spinner">

      <label class="block text-xs text-gray-500 font-mono mb-2 tracking-wider">DESCRIBE WHAT TO MONITOR</label>
      <textarea
        name="prompt"
        rows="3"
        placeholder="e.g. Alert me when the price of gold is > 30 USD"
        class="w-full bg-dark-bg border border-dark-border rounded p-3 text-sm font-mono text-gray-200 placeholder-gray-700 focus:outline-none focus:border-neon-green/50 focus:ring-1 focus:ring-neon-green/20 resize-none"
        required>{{ prompt or '' }}</textarea>

      {% if error %}
      <div class="mt-3 p-3 rounded border border-red-500/20 bg-red-500/5 text-red-400 text-xs font-mono">
        ⚠ {{ error }}
      </div>
      {% endif %}

      <div class="flex items-center justify-between mt-4">
        <span id="create-spinner" class="htmx-indicator text-neon-green text-xs font-mono animate-pulse">
          PARSING PROMPT...
        </span>
        <button type="submit"
          class="px-4 py-2 bg-neon-green text-black font-bold text-xs rounded tracking-wider hover:bg-neon-green/90 transition-all">
          CREATE SIGNAL
        </button>
      </div>
    </form>
  </div>
</div>
```

**Step 3: Create `src/templates/dashboard.html`**

```html
{% extends "base.html" %}
{% block title %}Dashboard — Signals{% endblock %}
{% block content %}

<div class="flex items-center justify-between mb-8">
  <div>
    <h1 class="text-2xl font-bold text-white tracking-wider">DASHBOARD</h1>
    <p class="text-gray-600 text-sm font-mono mt-1">{{ signals | length }} signal{% if signals | length != 1 %}s{% endif %} active</p>
  </div>
  <button
    hx-get="/partials/create-modal"
    hx-target="body"
    hx-swap="beforeend"
    class="flex items-center gap-2 px-4 py-2 bg-neon-green/10 border border-neon-green/30 text-neon-green text-xs font-mono rounded hover:bg-neon-green/20 transition-all">
    <span class="text-lg leading-none">+</span> NEW SIGNAL
  </button>
</div>

{% if not signals %}
<div class="text-center py-24 border border-dashed border-dark-border rounded-lg">
  <div class="text-gray-700 text-5xl mb-4">⬡</div>
  <p class="text-gray-600 font-mono text-sm mb-6">No signals yet. Create your first one.</p>
  <button
    hx-get="/partials/create-modal"
    hx-target="body"
    hx-swap="beforeend"
    class="px-6 py-3 border border-neon-green/30 text-neon-green text-xs font-mono rounded hover:bg-neon-green/10 transition-all">
    + CREATE SIGNAL
  </button>
</div>
{% else %}
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
  {% for signal in signals %}
    {% include "partials/signal_card.html" %}
  {% endfor %}
</div>
{% endif %}

{% endblock %}
```

**Step 4: Add partial endpoint to `src/routes/dashboard.py`**

Add this route to `src/routes/dashboard.py`:

```python
@router.get("/partials/create-modal", response_class=HTMLResponse)
async def create_modal_partial(request: Request):
    return templates.TemplateResponse(
        "partials/create_modal.html", {"request": request}
    )
```

**Step 5: Commit**

```bash
git add src/templates/ src/routes/dashboard.py
git commit -m "feat: add dashboard, signal card, and create modal templates"
```

---

## Task 14: Signal Detail Template

**Files:**
- Create: `src/templates/signal_detail.html`

**Step 1: Create `src/templates/signal_detail.html`**

```html
{% extends "base.html" %}
{% block title %}{{ signal.name }} — Signals{% endblock %}
{% block content %}

<div class="mb-6">
  <a href="/app" class="text-gray-600 hover:text-neon-green text-xs font-mono transition-colors">← DASHBOARD</a>
</div>

<div class="grid grid-cols-1 lg:grid-cols-3 gap-6">

  <!-- Left: Signal config -->
  <div class="lg:col-span-1 space-y-4">

    <!-- Status card -->
    <div class="p-5 rounded-lg border border-dark-border bg-dark-card">
      <div class="flex items-center gap-2 mb-3">
        <span class="text-xs font-mono
          {% if signal.status == 'active' %}text-neon-green{% elif signal.status == 'paused' %}text-yellow-400{% else %}text-red-400{% endif %}
          pulse-dot">
          {{ signal.status | upper }}
        </span>
        {% if signal.alert_triggered %}
        <span class="text-xs px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20">ALERT TRIGGERED</span>
        {% endif %}
      </div>
      <h1 class="text-xl font-bold text-white mb-1">{{ signal.name }}</h1>
      {% if signal.last_value is not none %}
      <div class="flex items-end gap-1 mt-4">
        <span class="text-4xl font-bold text-neon-blue">{{ "%.2f"|format(signal.last_value) }}</span>
        {% if signal.parsed.unit %}
        <span class="text-gray-500 text-sm mb-1">{{ signal.parsed.unit }}</span>
        {% endif %}
      </div>
      {% else %}
      <p class="text-gray-600 text-sm font-mono mt-4">No data yet</p>
      {% endif %}
      <p class="text-gray-600 text-xs font-mono mt-2">
        Condition: <span class="text-gray-400">{{ signal.parsed.condition }} {{ signal.parsed.threshold }} {{ signal.parsed.unit or '' }}</span>
      </p>
    </div>

    <!-- Edit form -->
    <div class="p-5 rounded-lg border border-dark-border bg-dark-card">
      <h2 class="text-xs font-mono text-gray-500 tracking-wider mb-4">EDIT SIGNAL</h2>

      {% if error %}
      <div class="mb-3 p-3 rounded border border-red-500/20 bg-red-500/5 text-red-400 text-xs font-mono">⚠ {{ error }}</div>
      {% endif %}

      <form method="POST" action="/signals/{{ signal.id }}/update">
        <label class="block text-xs text-gray-600 font-mono mb-1">PROMPT</label>
        <textarea name="prompt" rows="3" required
          class="w-full bg-dark-bg border border-dark-border rounded p-3 text-xs font-mono text-gray-200 placeholder-gray-700 focus:outline-none focus:border-neon-green/50 resize-none mb-4">{{ signal.prompt }}</textarea>

        <label class="block text-xs text-gray-600 font-mono mb-1">INTERVAL (minutes)</label>
        <select name="interval_minutes"
          class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50 mb-4">
          {% for mins in [5, 15, 30, 60, 120, 360, 720, 1440] %}
          <option value="{{ mins }}" {% if signal.interval_minutes == mins %}selected{% endif %}>
            {{ mins }} min{% if mins >= 60 %} ({{ mins // 60 }}h){% endif %}
          </option>
          {% endfor %}
        </select>

        <div class="flex gap-2">
          <button type="submit" class="flex-1 py-2 bg-neon-green/10 border border-neon-green/30 text-neon-green text-xs font-mono rounded hover:bg-neon-green/20 transition-all">
            SAVE
          </button>
          <button type="button"
            hx-post="/signals/{{ signal.id }}/run-now"
            hx-target="#signal-card"
            hx-swap="outerHTML"
            class="px-3 py-2 border border-dark-border text-gray-500 text-xs font-mono rounded hover:border-neon-blue/30 hover:text-neon-blue transition-all">
            RUN
          </button>
        </div>
      </form>
    </div>

    <!-- Alert toggle -->
    <div id="signal-card" class="p-5 rounded-lg border border-dark-border bg-dark-card">
      <h2 class="text-xs font-mono text-gray-500 tracking-wider mb-3">ALERTS</h2>
      <button
        hx-post="/signals/{{ signal.id }}/toggle-alert"
        hx-target="#signal-card"
        hx-swap="outerHTML"
        class="w-full py-2 rounded text-xs font-mono border transition-all
               {% if signal.alert_enabled %}bg-neon-green/5 border-neon-green/20 text-neon-green hover:bg-neon-green/10{% else %}border-dark-border text-gray-600 hover:border-gray-500{% endif %}">
        {% if signal.alert_enabled %}ALERTS ENABLED — CLICK TO DISABLE{% else %}ALERTS DISABLED — CLICK TO ENABLE{% endif %}
      </button>
    </div>
  </div>

  <!-- Right: Chart + History -->
  <div class="lg:col-span-2 space-y-6">

    <!-- Chart -->
    <div class="p-5 rounded-lg border border-dark-border bg-dark-card">
      <h2 class="text-xs font-mono text-gray-500 tracking-wider mb-4">HISTORICAL VALUES</h2>
      {% if runs and runs | selectattr('value') | list %}
      <canvas id="signalChart" height="120"></canvas>
      {% else %}
      <div class="text-center py-12 text-gray-700 font-mono text-sm">No data points yet</div>
      {% endif %}
    </div>

    <!-- Run history -->
    <div class="p-5 rounded-lg border border-dark-border bg-dark-card">
      <h2 class="text-xs font-mono text-gray-500 tracking-wider mb-4">RUN HISTORY</h2>
      {% if not runs %}
      <p class="text-gray-700 font-mono text-sm text-center py-8">No runs yet</p>
      {% else %}
      <div class="space-y-2 max-h-80 overflow-y-auto">
        {% for run in runs %}
        <div class="flex items-start gap-3 p-3 rounded border
          {% if run.alert_triggered %}border-red-500/20 bg-red-500/5{% elif run.status == 'error' %}border-yellow-500/20 bg-yellow-500/5{% else %}border-dark-border bg-dark-bg/50{% endif %}">
          <div class="flex-shrink-0 w-16 text-right">
            {% if run.value is not none %}
            <span class="text-neon-blue font-bold text-sm">{{ "%.2f"|format(run.value) }}</span>
            {% else %}
            <span class="text-gray-600 text-sm">—</span>
            {% endif %}
          </div>
          <div class="flex-1 min-w-0">
            <p class="text-gray-600 text-xs font-mono truncate">{{ run.raw_result[:100] }}</p>
          </div>
          <div class="flex-shrink-0 text-right">
            <span class="text-gray-700 text-xs font-mono">{{ run.ran_at.strftime('%m/%d %H:%M') }}</span>
            {% if run.alert_triggered %}
            <div class="text-red-400 text-xs">ALERT</div>
            {% endif %}
          </div>
        </div>
        {% endfor %}
      </div>
      {% endif %}
    </div>
  </div>
</div>

{% endblock %}

{% block scripts %}
{% set chart_runs = runs | selectattr('value') | list %}
{% if chart_runs %}
<script>
const ctx = document.getElementById('signalChart').getContext('2d');
const labels = {{ chart_runs | reverse | map(attribute='ran_at') | map('strftime', '%m/%d %H:%M') | list | tojson }};
const data = {{ chart_runs | reverse | map(attribute='value') | list | tojson }};

new Chart(ctx, {
  type: 'line',
  data: {
    labels,
    datasets: [{
      label: '{{ signal.parsed.topic }}',
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
      x: {
        grid: { color: '#1e1e2e' },
        ticks: { color: '#6b7280', font: { family: 'JetBrains Mono', size: 10 } }
      },
      y: {
        grid: { color: '#1e1e2e' },
        ticks: { color: '#6b7280', font: { family: 'JetBrains Mono', size: 10 } },
        {% if signal.parsed.threshold is not none %}
        plugins: {
          annotation: {
            annotations: {
              threshold: {
                type: 'line',
                yMin: {{ signal.parsed.threshold }},
                yMax: {{ signal.parsed.threshold }},
                borderColor: '#00ff88',
                borderWidth: 1,
                borderDash: [5, 5],
              }
            }
          }
        }
        {% endif %}
      }
    }
  }
});
</script>
{% endif %}
{% endblock %}
```

**Step 2: Commit**

```bash
git add src/templates/signal_detail.html
git commit -m "feat: add signal detail page with Chart.js history chart"
```

---

## Task 15: Jinja2 `strftime` filter + final wiring

**Files:**
- Modify: `src/main.py` (add Jinja2 filter, mount templates)
- Modify: `src/routes/signals.py` (fix import path)

**Step 1: Update `src/main.py` to register Jinja2 filter and templates globally**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from src.db import init_db
from src.services.scheduler import scheduler, load_all_signals
from src.routes import landing, dashboard
from src.routes import signals as signals_router


def strftime_filter(value, fmt="%Y-%m-%d %H:%M"):
    if value is None:
        return ""
    return value.strftime(fmt)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    scheduler.start()
    await load_all_signals()
    yield
    scheduler.shutdown()


app = FastAPI(title="Signals", lifespan=lifespan)

# Register custom Jinja2 filter on all routers' template instances
templates = Jinja2Templates(directory="src/templates")
templates.env.filters["strftime"] = strftime_filter

app.include_router(landing.router)
app.include_router(dashboard.router)
app.include_router(signals_router.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
```

**Step 2: Create a shared templates instance in `src/templates_config.py`**

```python
# src/templates_config.py
from fastapi.templating import Jinja2Templates


def strftime_filter(value, fmt="%Y-%m-%d %H:%M"):
    if value is None:
        return ""
    return value.strftime(fmt)


templates = Jinja2Templates(directory="src/templates")
templates.env.filters["strftime"] = strftime_filter
```

**Step 3: Update all routes to use the shared templates instance**

In `src/routes/landing.py`, `src/routes/dashboard.py`, `src/routes/signals.py`:

Replace:
```python
from fastapi.templating import Jinja2Templates
templates = Jinja2Templates(directory="src/templates")
```

With:
```python
from src.templates_config import templates
```

**Step 4: Run the app and verify it starts**

```bash
uv run uvicorn src.main:app --reload
```

Visit `http://localhost:8000` — landing page should render.
Visit `http://localhost:8000/app` — dashboard should render (empty state).

**Step 5: Commit**

```bash
git add src/templates_config.py src/routes/ src/main.py
git commit -m "feat: wire shared Jinja2 templates with strftime filter"
```

---

## Task 16: Run All Tests

**Step 1: Run full test suite**

```bash
uv run pytest tests/ -v
```

Expected: All tests PASS.

**Step 2: Manual smoke test**

```bash
uv run uvicorn src.main:app --reload
```

- Visit `http://localhost:8000` → landing page renders
- Visit `http://localhost:8000/app` → dashboard empty state renders
- Click "+ NEW SIGNAL" → modal opens
- Submit a prompt like "Alert me when Bitcoin price is over 100000 USD" → signal created
- Visit signal detail page → chart area visible

**Step 3: Final commit**

```bash
git add .
git commit -m "feat: complete Signals app v1 - all tests passing, full UI wired"
```

---

## Summary

| Task | Deliverable |
|---|---|
| 1 | uv scaffold, FastAPI health endpoint |
| 2 | Pydantic settings from .env |
| 3 | Beanie Signal + SignalRun models |
| 4 | MongoDB init in FastAPI lifespan |
| 5 | Gemini Flash prompt parser service |
| 6 | DuckDuckGo search service |
| 7 | Executor (condition evaluator + value extractor) |
| 8 | APScheduler signal job runner |
| 9 | Signal CRUD API routes |
| 10 | Landing + dashboard + detail routes |
| 11 | Base dark techy HTML template |
| 12 | Landing page template |
| 13 | Dashboard + signal card + create modal templates |
| 14 | Signal detail + Chart.js history chart |
| 15 | Shared Jinja2 templates + strftime filter |
| 16 | Full test suite + smoke test |
