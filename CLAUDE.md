# CLAUDE.md — Signals App

## Cleanup Rule (MANDATORY)

After every iteration, before committing:

- **Delete files** that are no longer used
- **Remove imports** that are no longer referenced
- **Remove dependencies** from `pyproject.toml` that are no longer imported anywhere
- **Remove dead code** — legacy paths, fallback functions, commented-out blocks

If you added something to make X work and X has been replaced, remove the old thing. No orphaned helpers, no "just in case" fallbacks.

---

## Stack

- FastAPI + Jinja2 + HTMX (server-rendered, no JS framework)
- Beanie / MongoDB (async ODM)
- LiteLLM (`litellm`, model `gemini/gemini-3.0-flash-preview`) for all LLM calls
- Playwright async (Chromium, headless) for source discovery and scheduled runs
- Brave Search API for URL discovery
- APScheduler for recurring signal execution
- `uv` for dependency management

## Key Files

| File | Purpose |
|------|---------|
| `src/models/signal.py` | Signal document model |
| `src/services/discovery.py` | Playwright source discovery (find URL → screenshot → extract value) |
| `src/services/executor.py` | Run a signal: Playwright → Gemini vision → evaluate condition |
| `src/services/llm.py` | Chat agent (`run_chat_turn`) + signal spec parsing |
| `src/routes/signals.py` | All signal routes including `/signals/chat` and `/signals/discover` |
| `src/templates/partials/create_modal.html` | Three-phase modal: Chat → Discovery → Confirmation |
| `src/config.py` | Settings loaded from `.env` |

## Signal Execution Path

Every signal run uses Playwright:

1. Navigate to `signal.source_url` (stored at creation time)
2. Screenshot `signal.source_selector` element, or full page if selector is `None`
3. Send screenshot + `signal.source_extraction_query` to Gemini vision
4. Parse float → evaluate condition → store result

There is no DuckDuckGo or text-extraction fallback. All signals must have `source_url` and `source_extraction_query` set.

## Intervals

All intervals are stored as `interval_minutes` but displayed and input as hours only (1h, 2h, 6h, 12h, 24h).

## LLM Calls — Structured Output

**Always use `response_format=SomePydanticModel` when calling `gemini_text` or `gemini_vision`**, unless the response is truly free-form text (e.g. a narrative summary where any string is valid).

Structured output:
- Guarantees valid JSON — no markdown code fence stripping
- Enforces exact field names — the model uses schema field names, not invented ones
- Eliminates all `json.loads` / parse error recovery code

Define a minimal Pydantic model for each LLM call's expected shape. Parse with `Model.model_validate_json(raw)`.

Skip structured output only when: (1) the response is a freeform string (prose summary, yes/no classifier returning a bool field is still structured), or (2) the model/provider doesn't support it.

## Code Style

- Python 3.14: use `X | None` not `Optional[X]`, use `list[T]` not `List[T]`
- No backwards-compatibility shims
- No commented-out code
- No docstrings on obvious functions
