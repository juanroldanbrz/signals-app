import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel as PydanticBaseModel

from src.crawling.agent import crawl
from src.models.signal import Signal, SignalStatus
from src.models.signal_run import RunStatus, SignalRun
from src.models.user import User
from src.services.auth import get_current_user
from src.services.executor import extract_from_url
from src.services.scheduler import _run_signal_job

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
    chart_type: Literal["line", "bar", "flag"] = "line"


@router.post("/signals/preview")
async def preview_signal(body: PreviewRequest, current_user: User = Depends(get_current_user)):
    if isinstance(current_user, RedirectResponse):
        return current_user

    queue: asyncio.Queue = asyncio.Queue()

    async def on_progress(msg: str) -> None:
        await queue.put({"type": "progress", "msg": msg})

    async def run_crawl() -> None:
        try:
            value, screenshot_bytes, raw, note = await crawl(
                body.url, body.extraction_query, body.chart_type, on_progress=on_progress
            )
            screenshot_url = _save_screenshot(screenshot_bytes) if screenshot_bytes else None

            if value is None:
                await queue.put({"type": "done", "error": raw, "screenshot_url": screenshot_url})
            elif body.chart_type == "flag":
                await queue.put({"type": "done", "value": value, "flag": value == 1.0, "screenshot_url": screenshot_url, "note": note})
            else:
                await queue.put({"type": "done", "value": value, "screenshot_url": screenshot_url, "note": note})
        except Exception as e:
            await queue.put({"type": "done", "error": f"Unexpected error: {str(e)[:200]}"})

    async def event_stream():
        asyncio.create_task(run_crawl())
        while True:
            event = await queue.get()
            event_type = event.pop("type")
            yield f"data: {json.dumps(event)}\n\n"
            if event_type == "done":
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class DigestPreviewRequest(PydanticBaseModel):
    source_urls: list[str]
    search_query: str = ""
    extraction_query: str = ""


@router.post("/signals/digest-preview")
async def digest_preview(body: DigestPreviewRequest, current_user: User = Depends(get_current_user)):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.services.digest_executor import run_digest

    queue: asyncio.Queue = asyncio.Queue()

    async def on_progress(msg: str) -> None:
        await queue.put({"type": "progress", "msg": msg})

    # Build a temporary signal-like object (no DB insert)
    class _TempSignal:
        source_urls = body.source_urls
        search_query = body.search_query or None
        source_extraction_query = body.extraction_query
        user_id = current_user.id

    async def run_task() -> None:
        try:
            result = await run_digest(_TempSignal(), on_progress=on_progress)
            if result["status"] == "error":
                await queue.put({"type": "done", "error": result["raw_result"]})
            else:
                content = result["content"]
                await queue.put({
                    "type": "done",
                    "summary": content.summary,
                    "key_points": content.key_points,
                    "sources": [s.model_dump() for s in content.sources],
                })
        except Exception as e:
            await queue.put({"type": "done", "error": f"Unexpected error: {str(e)[:200]}"})

    async def event_stream():
        asyncio.create_task(run_task())
        while True:
            event = await queue.get()
            event_type = event.pop("type")
            yield f"data: {json.dumps(event)}\n\n"
            if event_type == "done":
                break

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/signals/{signal_id}/card", response_class=HTMLResponse)
async def get_signal_card(request: Request, signal_id: PydanticObjectId, current_user: User = Depends(get_current_user)):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.templates_config import templates
    signal = await Signal.get(signal_id)
    if not signal or signal.user_id != current_user.id:
        return HTMLResponse(status_code=404)
    return templates.TemplateResponse(request, "partials/signal_card.html", {"signal": signal})


@router.post("/signals", response_class=HTMLResponse)
async def create_signal(
    request: Request,
    current_user: User = Depends(get_current_user),
    name: Annotated[str, Form()] = ...,
    signal_type: Annotated[str, Form()] = "monitor",
    source_url: Annotated[str, Form()] = "",
    source_urls_json: Annotated[str, Form()] = "[]",
    search_query: Annotated[str, Form()] = "",
    source_extraction_query: Annotated[str, Form()] = ...,
    chart_type: Annotated[str, Form()] = "line",
    interval_minutes: Annotated[int, Form()] = 60,
    source_initial_value: Annotated[str, Form()] = "",
):
    if isinstance(current_user, RedirectResponse):
        return current_user

    try:
        parsed_urls = json.loads(source_urls_json) if source_urls_json else []
    except Exception:
        parsed_urls = []

    if current_user.subscription_type == "FREE":
        existing_count = await Signal.find(Signal.user_id == current_user.id).count()
        if existing_count >= 1:
            from src.templates_config import templates
            return templates.TemplateResponse(
                request, "partials/plan_limit.html", {}, status_code=403,
            )
        interval_minutes = 1440

    signal = Signal(
        user_id=current_user.id,
        name=name,
        signal_type=signal_type,
        source_url=source_url,
        source_urls=parsed_urls,
        search_query=search_query or None,
        source_extraction_query=source_extraction_query,
        chart_type=chart_type,
        interval_minutes=interval_minutes,
    )
    await signal.insert()

    if signal_type == "monitor" and source_initial_value:
        try:
            initial_value = float(source_initial_value)
            run = SignalRun(
                user_id=current_user.id,
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

    signal.next_run_at = datetime.now(timezone.utc) + timedelta(minutes=signal.interval_minutes)
    await signal.save()

    if request.headers.get("HX-Request"):
        response = Response(status_code=200)
        response.headers["HX-Redirect"] = "/app"
        return response
    return RedirectResponse(url="/app", status_code=303)


@router.post("/signals/{signal_id}/delete")
async def delete_signal(signal_id: PydanticObjectId, current_user: User = Depends(get_current_user)):
    if isinstance(current_user, RedirectResponse):
        return current_user
    signal = await Signal.get(signal_id)
    if signal and signal.user_id == current_user.id:
        from src.models.app_event import AppEvent
        await SignalRun.find(SignalRun.signal_id == signal.id).delete()
        await AppEvent.find(AppEvent.signal_id == signal.id).delete()
        await signal.delete()
    return RedirectResponse(url="/app", status_code=303)


@router.post("/signals/{signal_id}/toggle-alert", response_class=HTMLResponse)
async def toggle_alert(request: Request, signal_id: PydanticObjectId, current_user: User = Depends(get_current_user)):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.templates_config import templates
    signal = await Signal.get(signal_id)
    if not signal or signal.user_id != current_user.id:
        return HTMLResponse(status_code=404)
    signal.alert_enabled = not signal.alert_enabled
    await signal.save()
    return templates.TemplateResponse(request, "partials/signal_card.html", {"signal": signal})


@router.post("/signals/{signal_id}/toggle-alert-page")
async def toggle_alert_page(signal_id: PydanticObjectId, current_user: User = Depends(get_current_user)):
    if isinstance(current_user, RedirectResponse):
        return current_user
    signal = await Signal.get(signal_id)
    if signal and signal.user_id == current_user.id:
        signal.alert_enabled = not signal.alert_enabled
        await signal.save()
    return RedirectResponse(url=f"/app/signals/{signal_id}", status_code=303)


@router.post("/signals/{signal_id}/run-now", response_class=HTMLResponse)
async def run_now(request: Request, signal_id: PydanticObjectId, current_user: User = Depends(get_current_user)):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.templates_config import templates
    signal = await Signal.get(signal_id)
    if not signal or signal.user_id != current_user.id:
        return HTMLResponse(status_code=404)
    signal.next_run_at = datetime.now(timezone.utc) + timedelta(minutes=signal.interval_minutes)
    await signal.save()
    asyncio.create_task(_run_signal_job(str(signal_id)))
    return templates.TemplateResponse(request, "partials/signal_card.html", {"signal": signal, "running": True})


@router.post("/signals/{signal_id}/update", response_class=HTMLResponse)
async def update_signal(
    request: Request,
    signal_id: PydanticObjectId,
    current_user: User = Depends(get_current_user),
    name: Annotated[str, Form()] = ...,
    interval_minutes: Annotated[int, Form()] = 60,
    source_extraction_query: Annotated[str, Form()] = "",
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.templates_config import templates
    signal = await Signal.get(signal_id)
    if not signal or signal.user_id != current_user.id:
        return RedirectResponse(url="/app", status_code=303)

    signal.name = name
    signal.interval_minutes = 1440 if current_user.subscription_type == "FREE" else interval_minutes
    if source_extraction_query:
        signal.source_extraction_query = source_extraction_query
    signal.consecutive_errors = 0
    signal.status = SignalStatus.ACTIVE
    signal.next_run_at = datetime.now(timezone.utc) + timedelta(minutes=signal.interval_minutes)
    await signal.save()

    runs = await SignalRun.find(SignalRun.signal_id == signal.id).sort("-ran_at").limit(20).to_list()
    return templates.TemplateResponse(request, "signal_detail.html", {"signal": signal, "runs": runs, "user": current_user})


@router.post("/signals/{signal_id}/alert-config", response_class=HTMLResponse)
async def update_alert_config(
    request: Request,
    signal_id: PydanticObjectId,
    current_user: User = Depends(get_current_user),
    condition_type: Annotated[str, Form()] = "",
    condition_threshold: Annotated[str, Form()] = "",
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.templates_config import templates
    signal = await Signal.get(signal_id)
    if not signal or signal.user_id != current_user.id:
        return HTMLResponse(status_code=404)

    signal.condition_type = condition_type if condition_type else None
    signal.condition_threshold = float(condition_threshold) if condition_threshold else None
    await signal.save()

    runs = await SignalRun.find(SignalRun.signal_id == signal.id).sort("-ran_at").limit(20).to_list()
    return templates.TemplateResponse(
        request, "signal_detail.html", {"signal": signal, "runs": runs, "user": current_user}
    )
