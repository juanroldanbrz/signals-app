# Digest Signals Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a "Digest" signal type that crawls URLs + optional Brave Search, summarises content with structured LLM output, and displays a text briefing with sources and dates — alongside the existing "Monitor" (numeric) signal type.

**Architecture:** Extend the `Signal` model with `signal_type`, `source_urls`, `search_query`. Branch execution in the scheduler. New services: `brave.py`, `digest_executor.py`. New `_html_to_markdown()` helper strips CSS/JS before LLM. Modal gets a type picker step 0; digest has its own form + SSE preview.

**Tech Stack:** FastAPI + Jinja2 + HTMX, Beanie/MongoDB, Playwright, BeautifulSoup4, html2text, httpx (Brave), LiteLLM gemini-2.5-flash structured output (Pydantic `response_format`)

---

## Task 1: Add Dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add deps**

In the `dependencies` list add:
```
"beautifulsoup4>=4.12.0",
"html2text>=2020.1.16",
```

**Step 2: Install**
```bash
uv sync
```
Expected: resolves without error.

**Step 3: Commit**
```bash
git add pyproject.toml uv.lock
git commit -m "chore: add beautifulsoup4 and html2text deps"
```

---

## Task 2: Gap-fill — test_scheduler.py

**Files:**
- Create: `tests/test_scheduler.py`

**Step 1: Write failing tests**
```python
# tests/test_scheduler.py
import pytest
from src.services.scheduler import evaluate_condition


def test_above_true():
    assert evaluate_condition("above", 100.0, 101.0, None) is True

def test_above_false():
    assert evaluate_condition("above", 100.0, 99.0, None) is False

def test_above_missing_threshold():
    assert evaluate_condition("above", None, 101.0, None) is False

def test_below_true():
    assert evaluate_condition("below", 100.0, 99.0, None) is True

def test_below_false():
    assert evaluate_condition("below", 100.0, 101.0, None) is False

def test_equals_true():
    assert evaluate_condition("equals", 42.0, 42.0, None) is True

def test_equals_false():
    assert evaluate_condition("equals", 42.0, 43.0, None) is False

def test_change_true():
    assert evaluate_condition("change", None, 42.0, 40.0) is True

def test_change_false_same_value():
    assert evaluate_condition("change", None, 42.0, 42.0) is False

def test_change_false_no_last_value():
    assert evaluate_condition("change", None, 42.0, None) is False

def test_none_condition_type():
    assert evaluate_condition(None, None, 42.0, None) is False
```

**Step 2: Run to verify they pass** (these test existing code)
```bash
uv run pytest tests/test_scheduler.py -v
```
Expected: 11 passed.

**Step 3: Commit**
```bash
git add tests/test_scheduler.py
git commit -m "test: gap-fill evaluate_condition branches"
```

---

## Task 3: Extend Signal + SignalRun Models

**Files:**
- Modify: `src/models/signal.py`
- Modify: `src/models/signal_run.py`
- Modify: `tests/test_models.py`

**Step 1: Write failing tests** (add to `tests/test_models.py`):
```python
async def test_signal_type_defaults_to_monitor():
    signal = Signal(
        user_id=ObjectId(),
        name="Test",
        source_url="https://example.com",
        source_extraction_query="price",
    )
    assert signal.signal_type == "monitor"
    assert signal.source_urls == []
    assert signal.search_query is None


async def test_digest_signal_fields():
    signal = Signal(
        user_id=ObjectId(),
        name="AI News",
        source_url="",
        source_extraction_query="latest AI news",
        signal_type="digest",
        source_urls=["https://techcrunch.com", "https://example.com"],
        search_query="AI safety 2026",
    )
    assert signal.signal_type == "digest"
    assert len(signal.source_urls) == 2
    assert signal.search_query == "AI safety 2026"


async def test_signal_run_digest_content_defaults_none():
    run = SignalRun(
        user_id=ObjectId(),
        signal_id=ObjectId(),
        value=None,
        alert_triggered=False,
        raw_result="ok",
    )
    assert run.digest_content is None
```

**Step 2: Run to verify they fail**
```bash
uv run pytest tests/test_models.py -v
```
Expected: 3 new tests fail with `ValidationError` / `AttributeError`.

**Step 3: Extend Signal model** (`src/models/signal.py`):
```python
class Signal(Document):
    user_id: PydanticObjectId
    name: str
    source_url: str
    source_extraction_query: str
    signal_type: Literal["monitor", "digest"] = "monitor"   # ADD
    source_urls: list[str] = []                              # ADD
    search_query: str | None = None                          # ADD
    chart_type: Literal["line", "bar", "flag"] = "line"
    # ... rest unchanged
```

**Step 4: Extend SignalRun model** (`src/models/signal_run.py`):
```python
class SignalRun(Document):
    # ... existing fields unchanged ...
    digest_content: str | None = None    # ADD — JSON string of DigestContent
```

**Step 5: Run tests**
```bash
uv run pytest tests/test_models.py -v
```
Expected: all pass.

**Step 6: Commit**
```bash
git add src/models/signal.py src/models/signal_run.py tests/test_models.py
git commit -m "feat: extend Signal with signal_type/source_urls/search_query; SignalRun with digest_content"
```

---

## Task 4: DigestContent Model

**Files:**
- Create: `src/models/digest.py`
- Create: `tests/test_digest_model.py`

**Step 1: Write failing tests**
```python
# tests/test_digest_model.py
import pytest
from src.models.digest import DigestContent, SourceRef


def test_source_ref_date_optional():
    ref = SourceRef(title="Article", url="https://example.com")
    assert ref.date is None


def test_digest_content_serializes():
    content = DigestContent(
        summary="AI is evolving fast.",
        key_points=["Point A", "Point B"],
        sources=[SourceRef(title="TechCrunch", url="https://techcrunch.com", date="2026-03-05")],
    )
    data = content.model_dump()
    assert data["summary"] == "AI is evolving fast."
    assert len(data["key_points"]) == 2
    assert data["sources"][0]["date"] == "2026-03-05"


def test_digest_content_roundtrips_json():
    content = DigestContent(
        summary="Summary text",
        key_points=["k1"],
        sources=[SourceRef(title="S", url="https://s.com", date="2026-01-01")],
    )
    json_str = content.model_dump_json()
    restored = DigestContent.model_validate_json(json_str)
    assert restored.summary == "Summary text"
    assert restored.sources[0].url == "https://s.com"
```

**Step 2: Run to verify they fail**
```bash
uv run pytest tests/test_digest_model.py -v
```
Expected: ImportError — module not found.

**Step 3: Create `src/models/digest.py`**
```python
from pydantic import BaseModel


class SourceRef(BaseModel):
    title: str
    url: str
    date: str | None = None


class DigestContent(BaseModel):
    summary: str
    key_points: list[str]
    sources: list[SourceRef]
```

**Step 4: Run tests**
```bash
uv run pytest tests/test_digest_model.py -v
```
Expected: 3 passed.

**Step 5: Commit**
```bash
git add src/models/digest.py tests/test_digest_model.py
git commit -m "feat: add DigestContent and SourceRef models"
```

---

## Task 5: Migration Script

**Files:**
- Create: `scripts/migrate_signal_type.py`

**Step 1: Create the script**
```python
# scripts/migrate_signal_type.py
"""
Idempotent migration: set signal_type="monitor" on all existing Signal documents
that were created before the signal_type field was added.

Run with: uv run python scripts/migrate_signal_type.py
"""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from src.config import settings


async def main() -> None:
    client = AsyncIOMotorClient(settings.mongo_uri)
    db = client[settings.mongo_db]
    result = await db["signals"].update_many(
        {"signal_type": {"$exists": False}},
        {"$set": {"signal_type": "monitor", "source_urls": [], "search_query": None}},
    )
    print(f"Updated {result.modified_count} signal(s) → signal_type='monitor'")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
```

**Step 2: Verify it's runnable** (without a real DB, just check it parses):
```bash
uv run python -c "import scripts.migrate_signal_type"
```
Expected: no error (or `ModuleNotFoundError` if `scripts/` not a package — add `scripts/__init__.py` if needed).

**Step 3: Commit**
```bash
git add scripts/
git commit -m "chore: migration script — backfill signal_type=monitor on existing signals"
```

---

## Task 6: Brave Search Service

**Files:**
- Create: `src/services/brave.py`
- Create: `tests/test_brave.py`

**Step 1: Write failing tests**
```python
# tests/test_brave.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.services.brave import brave_search


async def test_returns_empty_list_when_no_api_key():
    results = await brave_search("AI news", api_key="")
    assert results == []


async def test_parses_results_correctly():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "web": {
            "results": [
                {"title": "AI Article", "url": "https://example.com/ai", "age": "2 days ago"},
                {"title": "No Date", "url": "https://example.com/no-date"},
            ]
        }
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("src.services.brave.httpx.AsyncClient", return_value=mock_client):
        results = await brave_search("AI news", api_key="test-key")

    assert len(results) == 2
    assert results[0].title == "AI Article"
    assert results[0].url == "https://example.com/ai"
    assert results[0].date == "2 days ago"
    assert results[1].date is None


async def test_returns_empty_list_on_network_error():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))

    with patch("src.services.brave.httpx.AsyncClient", return_value=mock_client):
        results = await brave_search("AI news", api_key="test-key")

    assert results == []


async def test_returns_empty_list_on_empty_results():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"web": {"results": []}}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("src.services.brave.httpx.AsyncClient", return_value=mock_client):
        results = await brave_search("AI news", api_key="test-key")

    assert results == []
```

**Step 2: Run to verify they fail**
```bash
uv run pytest tests/test_brave.py -v
```
Expected: ImportError.

**Step 3: Create `src/services/brave.py`**
```python
import httpx
from src.models.digest import SourceRef

_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


async def brave_search(query: str, api_key: str, count: int = 5) -> list[SourceRef]:
    """Search Brave and return SourceRef list. Returns [] if no key or on any error."""
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _BRAVE_URL,
                headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                params={"q": query, "count": count},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                SourceRef(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    date=item.get("age") or None,
                )
                for item in data.get("web", {}).get("results", [])
            ]
    except Exception:
        return []
```

**Step 4: Run tests**
```bash
uv run pytest tests/test_brave.py -v
```
Expected: 4 passed.

**Step 5: Commit**
```bash
git add src/services/brave.py tests/test_brave.py
git commit -m "feat: Brave Search service wrapper"
```

---

## Task 7: HTML→Markdown + crawl_text

**Files:**
- Modify: `src/crawling/agent.py`
- Create: `tests/test_crawl_text.py`

**Step 1: Write failing tests**
```python
# tests/test_crawl_text.py
import pytest
from src.crawling.agent import _html_to_markdown


def test_strips_script_tags():
    html = "<html><body><script>alert('xss')</script><p>Safe content</p></body></html>"
    result = _html_to_markdown(html)
    assert "alert" not in result
    assert "Safe content" in result


def test_strips_style_tags():
    html = "<html><head><style>body { color: red; }</style></head><body><p>Text</p></body></html>"
    result = _html_to_markdown(html)
    assert "color: red" not in result
    assert "Text" in result


def test_strips_nav_footer_header():
    html = "<html><body><nav>Nav Menu</nav><header>Site Header</header><p>Article</p><footer>Footer</footer></body></html>"
    result = _html_to_markdown(html)
    assert "Nav Menu" not in result
    assert "Site Header" not in result
    assert "Footer" not in result
    assert "Article" in result


def test_preserves_links():
    html = '<html><body><a href="https://example.com">Read more</a></body></html>'
    result = _html_to_markdown(html)
    assert "https://example.com" in result
    assert "Read more" in result


def test_preserves_headings():
    html = "<html><body><h1>Main Title</h1><h2>Subtitle</h2><p>Paragraph</p></body></html>"
    result = _html_to_markdown(html)
    assert "Main Title" in result
    assert "Subtitle" in result


def test_truncates_to_max_length():
    html = "<html><body><p>" + "x" * 50000 + "</p></body></html>"
    result = _html_to_markdown(html)
    assert len(result) <= 32000


def test_empty_html_returns_empty_string():
    result = _html_to_markdown("")
    assert isinstance(result, str)
```

**Step 2: Run to verify they fail**
```bash
uv run pytest tests/test_crawl_text.py -v
```
Expected: ImportError (`_html_to_markdown` not found).

**Step 3: Add `_html_to_markdown` and `crawl_text` to `src/crawling/agent.py`**

Add imports at the top of `agent.py`:
```python
from datetime import datetime, timezone
from bs4 import BeautifulSoup, Comment
import html2text as _html2text
```

Add these two functions after the existing imports/helpers (before `crawl`):
```python
_MAX_TEXT_CHARS = 32_000


def _html_to_markdown(html: str) -> str:
    """Strip boilerplate tags and convert HTML to clean markdown."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
    converter = _html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.body_width = 0
    return converter.handle(str(soup))[:_MAX_TEXT_CHARS]


async def crawl_text(url: str) -> dict:
    """
    Navigate to URL with Playwright, extract full page text as clean markdown.
    Returns dict with keys: text, title, url, fetched_at, and optionally error.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="load", timeout=30000)
            except Exception:
                pass
            await page.wait_for_timeout(1000)
            html = await page.content()
            title = await page.title()
            await browser.close()
        return {
            "text": _html_to_markdown(html),
            "title": title,
            "url": url,
            "fetched_at": fetched_at,
        }
    except Exception as e:
        return {"text": "", "title": "", "url": url, "fetched_at": fetched_at, "error": str(e)[:200]}
```

**Step 4: Run tests**
```bash
uv run pytest tests/test_crawl_text.py -v
```
Expected: 7 passed.

**Step 5: Run full suite to check nothing broke**
```bash
uv run pytest tests/ -q --ignore=tests/test_integration.py
```
Expected: all pass.

**Step 6: Commit**
```bash
git add src/crawling/agent.py tests/test_crawl_text.py
git commit -m "feat: _html_to_markdown and crawl_text — clean page text extraction for digest signals"
```

---

## Task 8: gemini_text Structured Output

**Files:**
- Modify: `src/services/tracing.py`

**Step 1: Update `gemini_text` to accept `response_format`**

Change the function signature and body in `src/services/tracing.py`:
```python
async def gemini_text(name: str, prompt: str, response_format=None) -> str:
    model = settings.llm_model
    start = _now()
    kwargs = dict(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    if (key := _api_key()) is not None:
        kwargs["api_key"] = key
    if response_format is not None:
        kwargs["response_format"] = response_format
    response = await litellm.acompletion(**kwargs)
    text = response.choices[0].message.content
    _log_generation(name, model, {"prompt": prompt[:1000]}, text, start)
    return text
```

**Step 2: Run full suite** (no new tests needed — existing tests mock `gemini_text` so the signature change is backwards compatible):
```bash
uv run pytest tests/ -q --ignore=tests/test_integration.py
```
Expected: all pass.

**Step 3: Commit**
```bash
git add src/services/tracing.py
git commit -m "feat: gemini_text supports response_format for structured output"
```

---

## Task 9: Digest Executor

**Files:**
- Create: `src/services/digest_executor.py`
- Create: `tests/test_digest_executor.py`

**Step 1: Write failing tests**
```python
# tests/test_digest_executor.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from src.models.digest import DigestContent, SourceRef
from src.models.signal import Signal


def _make_signal(**kwargs) -> Signal:
    defaults = dict(
        user_id=ObjectId(),
        name="AI News",
        source_url="",
        source_extraction_query="latest AI news",
        signal_type="digest",
        source_urls=["https://example.com"],
        search_query=None,
    )
    return Signal(**{**defaults, **kwargs})


async def test_run_digest_success():
    from src.services.digest_executor import run_digest

    sample = DigestContent(
        summary="AI advances rapidly in 2026.",
        key_points=["GPT-5 released", "Gemini 3 released"],
        sources=[SourceRef(title="Example", url="https://example.com", date="2026-03-05")],
    )
    signal = _make_signal()

    with patch("src.services.digest_executor.crawl_text", AsyncMock(return_value={
        "text": "Some article text about AI.", "title": "AI Article",
        "url": "https://example.com", "fetched_at": "2026-03-05T10:00:00+00:00",
    })), patch("src.services.digest_executor.gemini_text", AsyncMock(
        return_value=sample.model_dump_json()
    )):
        result = await run_digest(signal)

    assert result["status"] == "ok"
    content = DigestContent.model_validate_json(result["digest_content"])
    assert content.summary == "AI advances rapidly in 2026."
    assert len(content.key_points) == 2


async def test_run_digest_no_content_returns_error():
    from src.services.digest_executor import run_digest

    signal = _make_signal()

    with patch("src.services.digest_executor.crawl_text", AsyncMock(return_value={
        "text": "", "title": "", "url": "https://example.com",
        "fetched_at": "2026-03-05T10:00:00+00:00",
    })):
        result = await run_digest(signal)

    assert result["status"] == "error"
    assert result["digest_content"] is None


async def test_run_digest_emits_progress():
    from src.services.digest_executor import run_digest

    sample = DigestContent(summary="ok", key_points=[], sources=[])
    signal = _make_signal()
    messages = []

    async def capture(msg):
        messages.append(msg)

    with patch("src.services.digest_executor.crawl_text", AsyncMock(return_value={
        "text": "Content", "title": "Page", "url": "https://example.com",
        "fetched_at": "2026-03-05T10:00:00+00:00",
    })), patch("src.services.digest_executor.gemini_text", AsyncMock(
        return_value=sample.model_dump_json()
    )):
        await run_digest(signal, on_progress=capture)

    assert any("Crawling" in m for m in messages)
    assert any("Summary" in m or "ready" in m.lower() for m in messages)


async def test_run_digest_skips_brave_when_disabled():
    from src.services.digest_executor import run_digest

    sample = DigestContent(summary="ok", key_points=[], sources=[])
    signal = _make_signal(search_query="AI news")
    brave_mock = AsyncMock(return_value=[])

    mock_config = MagicMock()
    mock_config.brave_api_key = ""
    mock_config.brave_search_enabled = False

    with patch("src.services.digest_executor.crawl_text", AsyncMock(return_value={
        "text": "Content", "title": "Page", "url": "https://example.com",
        "fetched_at": "2026-03-05T10:00:00+00:00",
    })), patch("src.services.digest_executor.gemini_text", AsyncMock(
        return_value=sample.model_dump_json()
    )), patch("src.services.digest_executor.AppConfig.get_for_user", AsyncMock(
        return_value=mock_config
    )), patch("src.services.digest_executor.brave_search", brave_mock):
        await run_digest(signal)

    brave_mock.assert_not_called()


async def test_run_digest_calls_brave_when_enabled():
    from src.services.digest_executor import run_digest

    sample = DigestContent(summary="ok", key_points=[], sources=[])
    signal = _make_signal(search_query="AI news")

    mock_config = MagicMock()
    mock_config.brave_api_key = "test-key"
    mock_config.brave_search_enabled = True

    brave_results = [SourceRef(title="Web Result", url="https://web.com", date="2026-03-05")]
    brave_mock = AsyncMock(return_value=brave_results)

    with patch("src.services.digest_executor.crawl_text", AsyncMock(return_value={
        "text": "Content", "title": "Page", "url": "https://example.com",
        "fetched_at": "2026-03-05T10:00:00+00:00",
    })), patch("src.services.digest_executor.gemini_text", AsyncMock(
        return_value=sample.model_dump_json()
    )), patch("src.services.digest_executor.AppConfig.get_for_user", AsyncMock(
        return_value=mock_config
    )), patch("src.services.digest_executor.brave_search", brave_mock):
        await run_digest(signal)

    brave_mock.assert_called_once_with("AI news", "test-key")
```

**Step 2: Run to verify they fail**
```bash
uv run pytest tests/test_digest_executor.py -v
```
Expected: ImportError.

**Step 3: Create `src/services/digest_executor.py`**
```python
from datetime import datetime, timezone

from src.crawling.agent import crawl_text
from src.models.app_config import AppConfig
from src.models.digest import DigestContent, SourceRef
from src.models.signal import Signal
from src.services.brave import brave_search
from src.services.tracing import gemini_text

type ProgressCallback = None | object


async def run_digest(signal: Signal, on_progress=None) -> dict:
    """
    Crawl signal.source_urls, optionally call Brave Search, summarise with Gemini.
    Returns dict with keys: status, raw_result, digest_content (JSON str | None), content (DigestContent | None).
    """
    async def emit(msg: str) -> None:
        if on_progress is not None:
            await on_progress(msg)

    sources_text: list[str] = []
    source_refs: list[SourceRef] = []

    for url in signal.source_urls:
        await emit(f"Crawling {url} ...")
        result = await crawl_text(url)
        if result.get("text"):
            sources_text.append(
                f"## {result['title'] or url}\nURL: {url}\nFetched: {result['fetched_at']}\n\n{result['text']}"
            )
            source_refs.append(SourceRef(
                title=result["title"] or url,
                url=url,
                date=result["fetched_at"][:10],
            ))
            await emit(f"✓ {url} — {len(result['text']):,} chars")
        else:
            await emit(f"⚠ Could not fetch {url}")

    if signal.search_query:
        config = await AppConfig.get_for_user(signal.user_id)
        if config.brave_api_key and config.brave_search_enabled:
            await emit(f"Searching web: {signal.search_query} ...")
            search_results = await brave_search(signal.search_query, config.brave_api_key)
            for sr in search_results:
                sources_text.append(f"## {sr.title}\nURL: {sr.url}\nDate: {sr.date or 'unknown'}")
                source_refs.append(sr)
            await emit(f"✓ Found {len(search_results)} web results")

    if not sources_text:
        return {"status": "error", "raw_result": "No content fetched from any source", "digest_content": None, "content": None}

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    prompt = (
        f"Today is {today}. Summarise the following content for a quick briefing.\n"
        f"Topic: {signal.source_extraction_query or 'general summary'}\n\n"
        f"IMPORTANT: Include specific dates you find in the content. "
        f"Do not invent facts. Always cite the source URL.\n\n"
        f"---\n\n" + "\n\n---\n\n".join(sources_text)
    )

    await emit("Summarising with AI ...")
    raw = await gemini_text(name="digest_summary", prompt=prompt, response_format=DigestContent)

    try:
        content = DigestContent.model_validate_json(raw)
        existing_urls = {s.url for s in content.sources}
        for ref in source_refs:
            if ref.url not in existing_urls:
                content.sources.append(ref)
    except Exception:
        content = DigestContent(summary=raw[:500] if raw else "No summary", key_points=[], sources=source_refs)

    await emit("✓ Summary ready")
    return {
        "status": "ok",
        "raw_result": "digest",
        "digest_content": content.model_dump_json(),
        "content": content,
    }
```

**Step 4: Run tests**
```bash
uv run pytest tests/test_digest_executor.py -v
```
Expected: 5 passed.

**Step 5: Run full suite**
```bash
uv run pytest tests/ -q --ignore=tests/test_integration.py
```
Expected: all pass.

**Step 6: Commit**
```bash
git add src/services/digest_executor.py tests/test_digest_executor.py
git commit -m "feat: digest executor — crawl URLs + Brave + Gemini structured summary"
```

---

## Task 10: Scheduler Branching for Digest

**Files:**
- Modify: `src/services/scheduler.py`

**Step 1: Update `_run_signal_job`** in `src/services/scheduler.py`

Add import at top of function:
```python
from src.services.digest_executor import run_digest
```

Replace the `result = await run_signal(signal)` block:
```python
if signal.signal_type == "digest":
    result = await run_digest(signal)
else:
    result = await run_signal(signal)

value = result.get("value")
digest_content_str = result.get("digest_content")
```

Replace `alert_triggered` evaluation block:
```python
alert_triggered = False
if signal.signal_type == "monitor" and value is not None and signal.alert_enabled:
    alert_triggered = evaluate_condition(
        signal.condition_type,
        signal.condition_threshold,
        value,
        signal.last_value,
    )
```

Update `SignalRun(...)` creation to include `digest_content`:
```python
run = SignalRun(
    user_id=signal.user_id,
    signal_id=signal.id,
    value=value,
    alert_triggered=alert_triggered,
    raw_result=result["raw_result"],
    status=result["status"],
    digest_content=digest_content_str,
)
```

Wrap alert-sending in a monitor-only guard:
```python
if alert_triggered and signal.signal_type == "monitor":
    # ... existing telegram + email alert code
```

**Step 2: Run full suite**
```bash
uv run pytest tests/ -q --ignore=tests/test_integration.py
```
Expected: all pass.

**Step 3: Commit**
```bash
git add src/services/scheduler.py
git commit -m "feat: scheduler branches on signal_type — digest uses run_digest, no alert eval for digest"
```

---

## Task 11: Brave Config in AppConfig + Config Page

**Files:**
- Modify: `src/models/app_config.py`
- Modify: `src/routes/config.py`
- Modify: `src/templates/config.html`

**Step 1: Add Brave fields to `AppConfig`**
```python
class AppConfig(Document):
    user_id: PydanticObjectId
    email_enabled: bool = True
    telegram_enabled: bool = False
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    brave_api_key: str = ""          # ADD
    brave_search_enabled: bool = False  # ADD
    # ... Settings unchanged
```

**Step 2: Add route to `src/routes/config.py`**
```python
@router.post("/app/config/brave")
async def save_brave_config(
    current_user: User = Depends(get_current_user),
    brave_enabled: Annotated[str, Form()] = "",
    brave_api_key: Annotated[str, Form()] = "",
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.models.app_config import AppConfig
    config = await AppConfig.get_for_user(current_user.id)
    config.brave_search_enabled = brave_enabled == "on"
    config.brave_api_key = brave_api_key
    await config.save()
    return RedirectResponse(url="/app/config", status_code=303)
```

**Step 3: Add Brave card to `src/templates/config.html`**

Add after the Telegram card, before the closing `</div>` of the left column:
```html
<!-- Brave Search -->
<div class="p-5 rounded-lg border border-dark-border bg-dark-card">
  <h2 class="text-xs font-mono text-gray-500 tracking-wider mb-4">BRAVE SEARCH</h2>
  <p class="text-xs font-mono text-gray-700 mb-4">Used by Digest signals to fetch web search results alongside your URLs.</p>
  <form method="POST" action="/app/config/brave">
    <label class="flex items-center justify-between mb-4 cursor-pointer">
      <span class="text-xs font-mono text-gray-400">Enable Brave Search</span>
      <input type="checkbox" name="brave_enabled" value="on" {% if config.brave_search_enabled %}checked{% endif %}
        class="accent-neon-green w-4 h-4 cursor-pointer" />
    </label>
    <label class="block text-xs text-gray-600 font-mono mb-1">API KEY</label>
    <input name="brave_api_key" type="password" value="{{ config.brave_api_key }}"
      placeholder="BSA..."
      class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-green/50 mb-4" />
    <button type="submit"
      class="w-full py-2 bg-neon-green/10 border border-neon-green/30 text-neon-green text-xs font-mono rounded hover:bg-neon-green/20 transition-all">
      SAVE
    </button>
  </form>
</div>
```

**Step 4: Run full suite**
```bash
uv run pytest tests/ -q --ignore=tests/test_integration.py
```
Expected: all pass.

**Step 5: Commit**
```bash
git add src/models/app_config.py src/routes/config.py src/templates/config.html
git commit -m "feat: Brave Search config — AppConfig fields, /app/config/brave route, config page card"
```

---

## Task 12: Digest Preview SSE Endpoint

**Files:**
- Modify: `src/routes/signals.py`
- Modify: `tests/test_routes_signals.py`

**Step 1: Write failing tests** (add to `tests/test_routes_signals.py`):
```python
async def test_digest_preview_streams_and_returns_content(client):
    c, user = client
    from src.models.digest import DigestContent, SourceRef

    sample = DigestContent(
        summary="AI is advancing.",
        key_points=["Point A"],
        sources=[SourceRef(title="Example", url="https://example.com", date="2026-03-05")],
    )

    with patch("src.routes.signals.run_digest", AsyncMock(return_value={
        "status": "ok",
        "raw_result": "digest",
        "digest_content": sample.model_dump_json(),
        "content": sample,
    })):
        resp = await c.post(
            "/signals/digest-preview",
            json={"source_urls": ["https://example.com"], "search_query": "", "extraction_query": "AI news"},
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


async def test_digest_preview_returns_error_on_failure(client):
    c, user = client

    with patch("src.routes.signals.run_digest", AsyncMock(return_value={
        "status": "error",
        "raw_result": "No content fetched",
        "digest_content": None,
        "content": None,
    })):
        resp = await c.post(
            "/signals/digest-preview",
            json={"source_urls": ["https://example.com"], "search_query": "", "extraction_query": "AI news"},
        )

    assert resp.status_code == 200
    body = resp.text
    assert "error" in body or "No content" in body
```

**Step 2: Run to verify they fail**
```bash
uv run pytest tests/test_routes_signals.py::test_digest_preview_streams_and_returns_content tests/test_routes_signals.py::test_digest_preview_returns_error_on_failure -v
```
Expected: 404 or AttributeError.

**Step 3: Add endpoint to `src/routes/signals.py`**

Add import at top:
```python
from src.services.digest_executor import run_digest
```

Add class and route:
```python
class DigestPreviewRequest(PydanticBaseModel):
    source_urls: list[str]
    search_query: str = ""
    extraction_query: str = ""


@router.post("/signals/digest-preview")
async def preview_digest(
    body: DigestPreviewRequest,
    current_user: User = Depends(get_current_user),
):
    if isinstance(current_user, RedirectResponse):
        return current_user

    queue: asyncio.Queue = asyncio.Queue()

    async def on_progress(msg: str) -> None:
        await queue.put({"type": "progress", "msg": msg})

    async def run() -> None:
        temp_signal = Signal(
            user_id=current_user.id,
            name="preview",
            source_url="",
            source_extraction_query=body.extraction_query,
            signal_type="digest",
            source_urls=body.source_urls,
            search_query=body.search_query or None,
        )
        try:
            result = await run_digest(temp_signal, on_progress=on_progress)
            await queue.put({"type": "done", **{k: v for k, v in result.items() if k != "content"}})
        except Exception as e:
            await queue.put({"type": "done", "error": str(e)[:200]})
        finally:
            await queue.put(None)

    asyncio.create_task(run())

    async def generate():
        while True:
            item = await queue.get()
            if item is None:
                break
            event_type = item.pop("type", "progress")
            if event_type == "progress":
                yield f"data: {json.dumps({'msg': item['msg']})}\n\n"
            else:
                yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")
```

**Step 4: Run tests**
```bash
uv run pytest tests/test_routes_signals.py -v
```
Expected: all pass.

**Step 5: Commit**
```bash
git add src/routes/signals.py tests/test_routes_signals.py
git commit -m "feat: digest preview SSE endpoint /signals/digest-preview"
```

---

## Task 13: Signal Creation Route — Handle Digest Type

**Files:**
- Modify: `src/routes/signals.py`
- Modify: `tests/test_routes_signals.py`

**Step 1: Write failing test** (add to `tests/test_routes_signals.py`):
```python
async def test_create_digest_signal(client):
    c, user = client

    resp = await c.post("/signals", data={
        "signal_type": "digest",
        "name": "AI News Digest",
        "source_urls": ["https://example.com", "https://techcrunch.com"],
        "search_query": "AI safety",
        "extraction_query": "latest AI news",
        "interval_minutes": "60",
    })

    assert resp.status_code in (200, 303)
    signal = await Signal.find_one(Signal.name == "AI News Digest")
    assert signal is not None
    assert signal.signal_type == "digest"
    assert "https://example.com" in signal.source_urls
    assert signal.search_query == "AI safety"
```

**Step 2: Run to verify it fails**
```bash
uv run pytest tests/test_routes_signals.py::test_create_digest_signal -v
```

**Step 3: Update `POST /signals` route in `src/routes/signals.py`**

Find the existing `create_signal` function and add form parameters + branching:
```python
@router.post("/signals", response_class=HTMLResponse)
async def create_signal(
    request: Request,
    current_user: User = Depends(get_current_user),
    signal_type: Annotated[str, Form()] = "monitor",
    name: Annotated[str, Form()] = "",
    # monitor fields
    source_url: Annotated[str, Form()] = "",
    source_extraction_query: Annotated[str, Form()] = "",
    chart_type: Annotated[str, Form()] = "line",
    source_initial_value: Annotated[str, Form()] = "",
    # digest fields
    source_urls: Annotated[list[str], Form()] = [],
    search_query: Annotated[str, Form()] = "",
    extraction_query: Annotated[str, Form()] = "",
    # shared
    interval_minutes: Annotated[int, Form()] = 60,
):
    if isinstance(current_user, RedirectResponse):
        return current_user

    interval = 1440 if current_user.subscription_type == "FREE" else interval_minutes

    if signal_type == "digest":
        clean_urls = [u.strip() for u in source_urls if u.strip()]
        signal = Signal(
            user_id=current_user.id,
            name=name or "Digest",
            source_url="",
            source_extraction_query=extraction_query or search_query or name,
            signal_type="digest",
            source_urls=clean_urls,
            search_query=search_query or None,
            interval_minutes=interval,
        )
    else:
        initial_value = float(source_initial_value) if source_initial_value else None
        signal = Signal(
            user_id=current_user.id,
            name=name or source_url,
            source_url=source_url,
            source_extraction_query=source_extraction_query,
            chart_type=chart_type,
            interval_minutes=interval,
            last_value=initial_value,
            signal_type="monitor",
        )

    await signal.insert()
    return RedirectResponse(url="/app", status_code=303)
```

**Step 4: Run tests**
```bash
uv run pytest tests/test_routes_signals.py -v
```
Expected: all pass.

**Step 5: Commit**
```bash
git add src/routes/signals.py tests/test_routes_signals.py
git commit -m "feat: POST /signals handles digest type — source_urls, search_query, extraction_query"
```

---

## Task 14: Signal Card — Digest Display

**Files:**
- Modify: `src/templates/partials/signal_card.html`

**Step 1: Update the card template**

The card currently always shows `signal.last_value` and `signal.source_extraction_query`. Add branching at the top:

Replace the query line and value block with:
```html
{% if signal.signal_type == 'digest' %}
  <!-- Digest badge -->
  <div class="flex items-center gap-2 mb-1">
    <span class="text-xs font-mono text-{{ sc }} pulse-dot">{{ signal.status.value | upper }}</span>
    <span class="text-xs px-2 py-0.5 rounded bg-neon-blue/10 text-neon-blue border border-neon-blue/20 font-mono">DIGEST</span>
  </div>
  <h3 class="font-bold text-white text-sm mb-3">{{ signal.name }}</h3>

  <!-- Latest digest summary (from last run's digest_content) -->
  {% if signal.last_digest_summary %}
  <p class="text-gray-400 text-xs font-mono mb-4 leading-relaxed border-l-2 border-neon-blue/30 pl-3">
    {{ signal.last_digest_summary[:200] }}{% if signal.last_digest_summary | length > 200 %}…{% endif %}
  </p>
  {% else %}
  <p class="text-gray-600 text-xs font-mono mb-4">— no digest yet —</p>
  {% endif %}

  <div class="flex items-center justify-between text-xs text-gray-600 font-mono mb-4">
    <span>{{ signal.source_urls | length }} source{% if signal.source_urls | length != 1 %}s{% endif %}</span>
    <span>{% if signal.last_run_at %}updated {{ signal.last_run_at | strftime('%H:%M') }}{% else %}not run yet{% endif %}</span>
    <span>every {{ signal.interval_minutes // 60 }}h</span>
  </div>

{% else %}
  <!-- Monitor: existing display -->
  <div class="flex items-center gap-2 mb-1">
    <span class="text-xs font-mono text-{{ sc }} pulse-dot">{{ signal.status.value | upper }}</span>
    {% if signal.alert_triggered %}
    <span class="text-xs px-2 py-0.5 rounded bg-red-500/10 text-red-400 border border-red-500/20 font-mono">ALERT</span>
    {% endif %}
  </div>
  <h3 class="font-bold text-white text-sm">{{ signal.name }}</h3>

  <p class="text-gray-500 text-xs font-mono mb-4 leading-relaxed border-l-2 border-dark-border pl-3">
    {{ signal.source_extraction_query[:80] }}{% if signal.source_extraction_query | length > 80 %}...{% endif %}
  </p>

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

  <div class="flex items-center justify-between text-xs text-gray-600 font-mono mb-4">
    <span>{% if signal.last_run_at %}checked {{ signal.last_run_at | strftime('%H:%M') }}{% else %}not run yet{% endif %}</span>
    <span>every {{ signal.interval_minutes // 60 }}h</span>
  </div>
{% endif %}
```

Also add a `last_digest_summary` property to `Signal` model (`src/models/signal.py`) — a transient field set by the dashboard route, OR just pass it through Jinja. The simplest approach: add a `last_digest_summary: str | None = None` field to `Signal` (not persisted, just for template). Actually better to compute it in the dashboard route and inject into template context.

**Simplest approach — add to Signal model as a non-persisted property:**

Actually, the cleanest approach is to just leave it as a computed field the **dashboard route** populates. Update `src/routes/dashboard.py` to fetch the latest `SignalRun.digest_content` for each digest signal and attach a `last_digest_summary` attribute.

In `src/routes/dashboard.py`, after fetching signals:
```python
# For digest signals, attach latest summary for card display
for signal in signals:
    if signal.signal_type == "digest":
        latest_run = await SignalRun.find(
            SignalRun.signal_id == signal.id,
            SignalRun.digest_content != None,
        ).sort("-ran_at").limit(1).first_or_none()
        if latest_run and latest_run.digest_content:
            from src.models.digest import DigestContent
            try:
                content = DigestContent.model_validate_json(latest_run.digest_content)
                signal.last_digest_summary = content.summary
            except Exception:
                signal.last_digest_summary = None
        else:
            signal.last_digest_summary = None
    else:
        signal.last_digest_summary = None
```

Add `last_digest_summary: str | None = None` to `Signal` (not stored in DB — use Pydantic `model_config` to allow extra or just add the field with `exclude=True`).

Actually, the simplest way without modifying the Signal model: pass a separate dict to the template. Update the dashboard template context to include `digest_summaries: dict[str, str]` keyed by signal id, and access it in the card via `digest_summaries.get(signal.id | string)`.

**Use the dict approach** — no model change needed:

In `dashboard.py`:
```python
digest_summaries = {}
for signal in signals:
    if signal.signal_type == "digest":
        from src.models.signal_run import SignalRun
        from src.models.digest import DigestContent
        run = await SignalRun.find(
            SignalRun.signal_id == signal.id
        ).sort("-ran_at").limit(1).first_or_none()
        if run and run.digest_content:
            try:
                content = DigestContent.model_validate_json(run.digest_content)
                digest_summaries[str(signal.id)] = content.summary
            except Exception:
                pass

return templates.TemplateResponse(request, "dashboard.html", {
    "signals": signals,
    "user": current_user,
    "digest_summaries": digest_summaries,
})
```

In `signal_card.html`, replace `signal.last_digest_summary` with `digest_summaries.get(signal.id | string, "")`.

**Step 2: Run full suite**
```bash
uv run pytest tests/ -q --ignore=tests/test_integration.py
```
Expected: all pass.

**Step 3: Commit**
```bash
git add src/templates/partials/signal_card.html src/routes/dashboard.py
git commit -m "feat: signal card shows digest badge, summary preview, and source count"
```

---

## Task 15: Signal Detail Page — Digest View

**Files:**
- Modify: `src/templates/signal_detail.html`
- Modify: `src/routes/signals.py` (signal detail GET route — pass `digest_content`)

**Step 1: Update the signal detail GET route** in `src/routes/signals.py`

Find `GET /app/signals/{signal_id}` and add digest content loading:
```python
digest_content = None
if signal.signal_type == "digest":
    latest_run = await SignalRun.find(
        SignalRun.signal_id == signal.id,
        SignalRun.digest_content != None,
    ).sort("-ran_at").limit(1).first_or_none()
    if latest_run and latest_run.digest_content:
        from src.models.digest import DigestContent
        try:
            digest_content = DigestContent.model_validate_json(latest_run.digest_content)
        except Exception:
            pass

return templates.TemplateResponse(request, "signal_detail.html", {
    "signal": signal,
    "runs": runs,
    "user": current_user,
    "digest_content": digest_content,
})
```

**Step 2: Update `signal_detail.html`** — add digest branching

In the left column, hide the alert section for digest signals:
```html
{% if signal.signal_type != 'digest' %}
<!-- ALERTS section (existing) -->
...
{% endif %}
```

In the right column, replace the chart + history section:
```html
{% if signal.signal_type == 'digest' %}

  <!-- Latest digest -->
  <div class="p-5 rounded-lg border border-dark-border bg-dark-card">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-xs font-mono text-gray-500 tracking-wider">LATEST DIGEST</h2>
      <span class="text-xs font-mono text-yellow-400/60 border border-yellow-400/20 rounded px-2 py-0.5">⚠ AI-generated — verify before acting</span>
    </div>
    {% if digest_content %}
      <p class="text-gray-200 text-sm leading-relaxed mb-4">{{ digest_content.summary }}</p>
      {% if digest_content.key_points %}
      <ul class="space-y-1 mb-4">
        {% for point in digest_content.key_points %}
        <li class="text-gray-400 text-xs font-mono flex gap-2"><span class="text-neon-green">›</span> {{ point }}</li>
        {% endfor %}
      </ul>
      {% endif %}
      {% if digest_content.sources %}
      <div class="border-t border-dark-border pt-3">
        <p class="text-xs font-mono text-gray-600 mb-2">SOURCES</p>
        <div class="space-y-1">
          {% for source in digest_content.sources %}
          <div class="flex items-start gap-2 text-xs font-mono">
            <span class="text-gray-700 shrink-0">{{ source.date or '—' }}</span>
            <a href="{{ source.url }}" target="_blank" rel="noopener"
               class="text-neon-blue hover:underline truncate">{{ source.title or source.url }}</a>
          </div>
          {% endfor %}
        </div>
      </div>
      {% endif %}
    {% else %}
      <p class="text-gray-600 font-mono text-sm text-center py-8">No digest yet — run signal to generate</p>
    {% endif %}
  </div>

  <!-- Digest history -->
  <div class="p-5 rounded-lg border border-dark-border bg-dark-card">
    <h2 class="text-xs font-mono text-gray-500 tracking-wider mb-4">HISTORY</h2>
    {% if not runs %}
    <p class="text-gray-700 font-mono text-sm text-center py-8">No runs yet</p>
    {% else %}
    <div class="space-y-2 max-h-80 overflow-y-auto">
      {% for run in runs %}
      {% if run.digest_content %}
      {% set rc = run.digest_content | fromjson %}
      <div class="p-3 rounded border border-dark-border bg-dark-bg/50">
        <div class="flex items-center justify-between mb-1">
          <span class="text-gray-700 text-xs font-mono">{{ run.ran_at | strftime('%m/%d %H:%M') }}</span>
          <span class="text-xs font-mono text-gray-600">{{ rc.sources | length }} sources</span>
        </div>
        <p class="text-gray-400 text-xs leading-relaxed">{{ rc.summary[:150] }}{% if rc.summary | length > 150 %}…{% endif %}</p>
      </div>
      {% endif %}
      {% endfor %}
    </div>
    {% endif %}
  </div>

{% else %}
  <!-- Monitor: existing chart + run history (unchanged) -->
  ...
{% endif %}
```

Note: The `fromjson` Jinja filter must be registered. Add to `src/templates_config.py`:
```python
import json
templates.env.filters["fromjson"] = json.loads
```

**Step 2: Run full suite**
```bash
uv run pytest tests/ -q --ignore=tests/test_integration.py
```
Expected: all pass.

**Step 3: Commit**
```bash
git add src/templates/signal_detail.html src/routes/signals.py src/templates_config.py
git commit -m "feat: signal detail page shows digest content — summary, key points, sources, history"
```

---

## Task 16: Creation Modal — Type Picker + Digest Form

**Files:**
- Modify: `src/templates/partials/create_modal.html`

**Step 1: Restructure the modal**

The modal body becomes three phases controlled by JS:
- **Phase 0 — Type picker** (shown first)
- **Phase 1 — Monitor form** (existing, shown after picking Monitor)
- **Phase 1 — Digest form** (new, shown after picking Digest)

Replace the entire `create_modal.html` content:

**Type picker (Phase 0):**
```html
<!-- PHASE 0: Type picker -->
<div id="phase-picker" class="px-6 py-5">
  <p class="text-xs font-mono text-gray-500 mb-4">What kind of signal do you want to create?</p>
  <div class="grid grid-cols-2 gap-3">
    <button onclick="pickType('monitor')"
      class="p-4 rounded-lg border border-dark-border hover:border-neon-green/40 hover:bg-neon-green/5 transition-all text-left">
      <div class="text-neon-green text-xs font-mono font-bold mb-2">MONITOR</div>
      <div class="text-gray-400 text-xs leading-relaxed">Track a number. Get alerted when BTC drops below $50k, stock goes out, uptime falls.</div>
    </button>
    <button onclick="pickType('digest')"
      class="p-4 rounded-lg border border-dark-border hover:border-neon-blue/40 hover:bg-neon-blue/5 transition-all text-left">
      <div class="text-neon-blue text-xs font-mono font-bold mb-2">DIGEST</div>
      <div class="text-gray-400 text-xs leading-relaxed">Summarize content. Get a daily briefing on AI news, competitor updates, any topic.</div>
    </button>
  </div>
</div>
```

**Monitor form (Phase 1a) — wrapped in `id="phase-monitor" class="hidden"`:**
Existing form content, unchanged.

**Digest form (Phase 1b) — wrapped in `id="phase-digest" class="hidden"`:**
```html
<div id="phase-digest" class="hidden px-6 py-5">
  <button onclick="showPicker()" class="text-xs font-mono text-gray-600 hover:text-gray-300 mb-4 block">← back</button>
  <div class="space-y-4">
    <div>
      <label class="block text-xs text-gray-600 font-mono mb-1">NAME</label>
      <input id="d-name" type="text" placeholder="e.g. AI News Briefing"
        class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-blue/50" />
    </div>
    <div>
      <label class="block text-xs text-gray-600 font-mono mb-1">WHAT TO SUMMARISE</label>
      <input id="d-query" type="text" placeholder="e.g. Latest news about AI safety"
        class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-blue/50" />
    </div>
    <div>
      <label class="block text-xs text-gray-600 font-mono mb-1">SOURCE URLS</label>
      <div id="url-list" class="space-y-2"></div>
      <button type="button" onclick="addUrlRow()"
        class="mt-2 text-xs font-mono text-neon-blue hover:text-white transition-colors">+ Add URL</button>
    </div>
    <div>
      <label class="flex items-center gap-2 cursor-pointer mb-2">
        <input type="checkbox" id="d-brave-toggle" onchange="toggleBrave(this)"
          class="accent-neon-blue w-4 h-4" />
        <span class="text-xs font-mono text-gray-400">Web search (Brave)</span>
      </label>
      <div id="brave-query-row" class="hidden">
        <input id="d-brave-query" type="text" placeholder="Search query, e.g. AI safety news 2026"
          class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-blue/50" />
      </div>
    </div>
    <div>
      <label class="block text-xs text-gray-600 font-mono mb-1">REFRESH INTERVAL</label>
      {% if user.subscription_type == "FREE" %}
      <div class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-500 flex items-center justify-between">
        <span>24h</span>
        <a href="mailto:juan.roldan@bluggie.com?subject=Signals upgrade" class="text-neon-blue hover:text-neon-green transition-colors">Upgrade for 1h–12h</a>
      </div>
      <input type="hidden" id="d-interval" value="1440" />
      {% else %}
      <select id="d-interval"
        class="w-full bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-blue/50">
        <option value="60">1h</option>
        <option value="120">2h</option>
        <option value="360">6h</option>
        <option value="720">12h</option>
        <option value="1440">24h</option>
      </select>
      {% endif %}
    </div>
    <p id="digest-error" class="hidden text-red-400 text-xs font-mono"></p>
    <button id="digest-preview-btn" onclick="runDigestPreview()"
      class="w-full py-2 bg-neon-blue/10 border border-neon-blue/30 text-neon-blue text-xs font-mono rounded hover:bg-neon-blue/20 transition-all">
      PREVIEW
    </button>
  </div>

  <!-- Console -->
  <div id="digest-console" class="hidden mt-4">
    <div class="bg-black border border-dark-border rounded overflow-hidden">
      <div class="flex items-center gap-2 px-3 py-1.5 border-b border-dark-border">
        <span class="text-xs text-gray-600 font-mono tracking-wider">CONSOLE</span>
        <span id="digest-spinner" class="hidden text-neon-blue text-xs font-mono animate-pulse">●</span>
      </div>
      <div id="digest-console-output"
           class="px-3 py-2 font-mono text-xs text-neon-blue leading-relaxed h-56 overflow-y-auto overflow-x-hidden break-all">
      </div>
    </div>
  </div>
</div>
```

**Digest back face (preview result):**
```html
<div id="digest-card-back" style="backface-visibility: hidden; transform: rotateY(180deg); top: 0; left: 0; right: 0;" class="px-6 py-5 absolute">
  <div class="border border-dark-border rounded p-4 space-y-3 text-xs font-mono mb-5">
    <div class="text-gray-500 tracking-wider mb-3">DIGEST PREVIEW</div>
    <div class="text-yellow-400/70 text-xs mb-3">⚠ AI-generated — verify before acting</div>
    <p id="digest-preview-summary" class="text-gray-200 text-sm leading-relaxed"></p>
    <ul id="digest-preview-points" class="space-y-1 mt-2"></ul>
    <div id="digest-preview-sources" class="border-t border-dark-border pt-3 space-y-1 mt-3"></div>
  </div>

  <form id="digest-save-form" method="POST" action="/signals"
        hx-post="/signals" hx-target="#create-modal" hx-swap="outerHTML">
    <input type="hidden" name="signal_type" value="digest" />
    <input type="hidden" name="name" id="dsf-name" />
    <input type="hidden" name="extraction_query" id="dsf-query" />
    <input type="hidden" name="search_query" id="dsf-brave-query" />
    <input type="hidden" name="interval_minutes" id="dsf-interval" />
    <div id="dsf-urls-container"></div>

    <div class="flex gap-3">
      <button type="button" onclick="digestFlipBack()"
        class="flex-1 py-2 border border-dark-border text-gray-500 text-xs font-mono rounded hover:border-gray-500 hover:text-gray-300 transition-all">
        ← TRY AGAIN
      </button>
      <button type="submit"
        class="flex-1 py-2 bg-neon-blue text-black font-bold text-xs rounded tracking-wider hover:bg-neon-blue/90 transition-all">
        SAVE SIGNAL
      </button>
    </div>
  </form>
</div>
```

**JS additions (in the `<script>` block):**
```javascript
let _signalType = 'monitor';

window.pickType = function(type) {
  _signalType = type;
  document.getElementById('phase-picker').classList.add('hidden');
  if (type === 'monitor') {
    document.getElementById('phase-monitor').classList.remove('hidden');
  } else {
    document.getElementById('phase-digest').classList.remove('hidden');
    if (document.getElementById('url-list').children.length === 0) addUrlRow();
  }
};

window.showPicker = function() {
  document.getElementById('phase-monitor').classList.add('hidden');
  document.getElementById('phase-digest').classList.add('hidden');
  document.getElementById('phase-picker').classList.remove('hidden');
};

window.addUrlRow = function() {
  const list = document.getElementById('url-list');
  const row = document.createElement('div');
  row.className = 'flex gap-2';
  row.innerHTML = `
    <input type="url" placeholder="https://..."
      class="flex-1 bg-dark-bg border border-dark-border rounded p-2 text-xs font-mono text-gray-200 focus:outline-none focus:border-neon-blue/50 url-input" />
    <button type="button" onclick="this.parentElement.remove()" class="text-gray-600 hover:text-red-400 text-xs font-mono px-2">✕</button>`;
  list.appendChild(row);
};

window.toggleBrave = function(cb) {
  document.getElementById('brave-query-row').classList.toggle('hidden', !cb.checked);
};

window.runDigestPreview = async function() {
  const name = document.getElementById('d-name').value.trim();
  const query = document.getElementById('d-query').value.trim();
  const interval = document.getElementById('d-interval').value;
  const urlInputs = document.querySelectorAll('#url-list .url-input');
  const sourceUrls = Array.from(urlInputs).map(i => i.value.trim()).filter(Boolean);
  const braveEnabled = document.getElementById('d-brave-toggle').checked;
  const braveQuery = document.getElementById('d-brave-query').value.trim();
  const errEl = document.getElementById('digest-error');

  if (!query) { errEl.textContent = 'Topic/query is required.'; errEl.classList.remove('hidden'); return; }
  if (sourceUrls.length === 0 && !braveQuery) { errEl.textContent = 'Add at least one URL or enable web search.'; errEl.classList.remove('hidden'); return; }

  errEl.classList.add('hidden');
  const btn = document.getElementById('digest-preview-btn');
  btn.disabled = true; btn.textContent = '⟳ RUNNING...';
  const consoleEl = document.getElementById('digest-console');
  const output = document.getElementById('digest-console-output');
  output.innerHTML = '';
  consoleEl.classList.remove('hidden');
  document.getElementById('digest-spinner').classList.remove('hidden');

  const log = (msg, cls) => {
    const line = document.createElement('div');
    line.className = cls || 'text-neon-blue';
    line.textContent = '› ' + msg;
    output.appendChild(line);
    output.scrollTop = output.scrollHeight;
  };

  let data = null;
  try {
    const res = await fetch('/signals/digest-preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ source_urls: sourceUrls, search_query: braveQuery, extraction_query: query }),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const parts = buffer.split('\n\n');
      buffer = parts.pop();
      for (const part of parts) {
        const line = part.trim();
        if (!line.startsWith('data: ')) continue;
        try {
          const event = JSON.parse(line.slice(6));
          if (event.msg !== undefined) { log(event.msg); } else { data = event; }
        } catch (_) {}
      }
    }
  } catch (e) {
    log('⚠ Connection error', 'text-red-400');
  }

  document.getElementById('digest-spinner').classList.add('hidden');
  btn.disabled = false; btn.textContent = 'PREVIEW';

  if (!data || data.error || data.status === 'error') {
    log('⚠ ' + (data ? (data.error || data.raw_result) : 'No response'), 'text-red-400');
    return;
  }

  log('✓ Done.', 'text-gray-500');

  // Parse and display on back face
  let content = null;
  try { content = JSON.parse(data.digest_content); } catch (_) {}
  if (!content) { log('⚠ Could not parse digest content', 'text-red-400'); return; }

  document.getElementById('digest-preview-summary').textContent = content.summary || '';
  const pointsList = document.getElementById('digest-preview-points');
  pointsList.innerHTML = (content.key_points || []).map(p =>
    `<li class="text-gray-400 text-xs font-mono flex gap-2"><span class="text-neon-blue">›</span> ${p}</li>`
  ).join('');
  const sourcesEl = document.getElementById('digest-preview-sources');
  sourcesEl.innerHTML = (content.sources || []).map(s =>
    `<div class="flex items-start gap-2 text-xs font-mono"><span class="text-gray-700 shrink-0">${s.date || '—'}</span><a href="${s.url}" target="_blank" class="text-neon-blue hover:underline truncate">${s.title || s.url}</a></div>`
  ).join('');

  // Populate hidden save form
  document.getElementById('dsf-name').value = name || query;
  document.getElementById('dsf-query').value = query;
  document.getElementById('dsf-brave-query').value = braveQuery;
  document.getElementById('dsf-interval').value = interval;
  const urlsContainer = document.getElementById('dsf-urls-container');
  urlsContainer.innerHTML = sourceUrls.map(u =>
    `<input type="hidden" name="source_urls" value="${u}" />`
  ).join('');

  // Flip to back
  document.getElementById('digest-flip-inner').style.transform = 'rotateY(180deg)';
};

window.digestFlipBack = function() {
  document.getElementById('digest-flip-inner').style.transform = '';
};
```

Note: The digest form needs its own flip container (`id="digest-flip-inner"`), separate from the monitor one.

**Step 2: Run full suite**
```bash
uv run pytest tests/ -q --ignore=tests/test_integration.py
```
Expected: all pass.

**Step 3: Commit**
```bash
git add src/templates/partials/create_modal.html
git commit -m "feat: creation modal type picker + digest form with URL list, Brave toggle, SSE preview"
```

---

## Final Verification

```bash
uv run pytest tests/ -q --ignore=tests/test_integration.py
git log --oneline -15
```

Check the complete flow manually:
1. Open dashboard → click NEW SIGNAL → type picker appears
2. Pick DIGEST → fill name, query, add URL → PREVIEW → console streams → flip → SAVE
3. Dashboard shows DIGEST card with badge
4. Signal detail shows summary + sources (or "no digest yet" if not run)
5. Config page shows BRAVE SEARCH card
6. Run migration script against staging DB

---

**Plan complete and saved to `docs/plans/2026-03-05-digest-signals-plan.md`.**

Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** — Open a new session in the same repo with executing-plans, batch execution with checkpoints

Which approach?
