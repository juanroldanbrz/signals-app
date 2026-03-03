import asyncio
import base64
import functools
import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

import httpx
import litellm
from src.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Context propagation — trace_id flows through the async call stack
# ---------------------------------------------------------------------------
_trace_id_var: ContextVar[str | None] = ContextVar("lf_trace_id", default=None)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Langfuse HTTP client — fire-and-forget via asyncio.create_task
# ---------------------------------------------------------------------------
class _LFClient:
    def __init__(self, public_key: str, secret_key: str, host: str):
        credentials = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
        self._headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }
        self._url = f"{host.rstrip('/')}/api/public/ingestion"

    async def _flush(self, batch: list[dict]) -> None:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.post(
                    self._url,
                    headers=self._headers,
                    content=json.dumps({"batch": batch}),
                )
                if resp.status_code >= 400:
                    logger.debug("Langfuse HTTP %s: %s", resp.status_code, resp.text[:200])
        except Exception as exc:
            logger.debug("Langfuse send error: %s", exc)

    def send(self, batch: list[dict]) -> None:
        try:
            asyncio.get_running_loop().create_task(self._flush(batch))
        except RuntimeError:
            pass


_lf_client: _LFClient | None = None


def _lf() -> _LFClient | None:
    global _lf_client
    if _lf_client is None and settings.langfuse_public_key and settings.langfuse_secret_key:
        _lf_client = _LFClient(
            settings.langfuse_public_key,
            settings.langfuse_secret_key,
            settings.langfuse_host,
        )
    return _lf_client


# ---------------------------------------------------------------------------
# observe() decorator — wraps a coroutine in a Langfuse trace
# ---------------------------------------------------------------------------
def observe(*deco_args, **_deco_kwargs):
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            client = _lf()
            if client is None:
                return await fn(*args, **kwargs)

            existing = _trace_id_var.get()
            if existing is None:
                trace_id = _uid()
                token = _trace_id_var.set(trace_id)
                client.send([{
                    "id": _uid(),
                    "type": "trace-create",
                    "timestamp": _now(),
                    "body": {"id": trace_id, "name": fn.__name__},
                }])
            else:
                trace_id = existing
                token = None

            try:
                return await fn(*args, **kwargs)
            finally:
                if token is not None:
                    _trace_id_var.reset(token)

        return wrapper

    if deco_args and callable(deco_args[0]):
        return decorator(deco_args[0])
    return decorator


# ---------------------------------------------------------------------------
# Internal: log a generation event under the current trace
# ---------------------------------------------------------------------------
def _log_generation(
    name: str,
    model: str,
    input_data: str | dict,
    output: str | None,
    start: str,
) -> None:
    client = _lf()
    if client is None:
        return
    trace_id = _trace_id_var.get()
    if trace_id is None:
        return
    client.send([{
        "id": _uid(),
        "type": "generation-create",
        "timestamp": start,
        "body": {
            "id": _uid(),
            "traceId": trace_id,
            "name": name,
            "model": model,
            "input": input_data,
            "output": output[:2000] if output else None,
            "startTime": start,
            "endTime": _now(),
        },
    }])


# ---------------------------------------------------------------------------
# LiteLLM call wrappers — each one logs a Langfuse generation
# ---------------------------------------------------------------------------

async def gemini_vision(name: str, image: bytes, prompt: str, model: str = "gemini/gemini-3.0-flash-preview") -> str:
    start = _now()
    image_b64 = base64.b64encode(image).decode()
    response = await litellm.acompletion(
        model=model,
        api_key=settings.gemini_api_key,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    text = response.choices[0].message.content
    _log_generation(name, model, {"prompt": prompt[:1000], "image_bytes": len(image)}, text, start)
    return text


async def gemini_text(name: str, prompt: str, model: str = "gemini/gemini-3.0-flash-preview") -> str:
    start = _now()
    response = await litellm.acompletion(
        model=model,
        api_key=settings.gemini_api_key,
        messages=[{"role": "user", "content": prompt}],
    )
    text = response.choices[0].message.content
    _log_generation(name, model, {"prompt": prompt[:1000]}, text, start)
    return text
