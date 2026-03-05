from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.models.user import User
from src.services.auth import get_current_user

router = APIRouter()


@router.get("/app", response_class=HTMLResponse)
async def dashboard(request: Request, current_user: User = Depends(get_current_user)):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.templates_config import templates
    from src.models.signal import Signal
    from src.models.signal_run import SignalRun
    import json

    signals = await Signal.find(Signal.user_id == current_user.id).sort("-created_at").to_list()

    digest_summaries: dict[str, str] = {}
    for sig in signals:
        if sig.signal_type == "digest":
            latest_run = await SignalRun.find(
                SignalRun.signal_id == sig.id
            ).sort("-ran_at").limit(1).first_or_none()
            if latest_run and latest_run.digest_content:
                try:
                    data = json.loads(latest_run.digest_content)
                    digest_summaries[str(sig.id)] = data.get("summary", "")
                except Exception:
                    pass

    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"signals": signals, "user": current_user, "digest_summaries": digest_summaries},
    )


@router.get("/app/signals/{signal_id}", response_class=HTMLResponse)
async def signal_detail(request: Request, signal_id: PydanticObjectId, current_user: User = Depends(get_current_user)):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.templates_config import templates
    from src.models.signal import Signal
    from src.models.signal_run import SignalRun
    import json

    signal = await Signal.get(signal_id)
    if not signal or signal.user_id != current_user.id:
        return RedirectResponse(url="/app", status_code=303)
    runs = await SignalRun.find(
        SignalRun.signal_id == signal.id
    ).sort("-ran_at").limit(50).to_list()

    latest_digest = None
    if signal.signal_type == "digest" and runs:
        for run in runs:
            if run.digest_content:
                try:
                    latest_digest = json.loads(run.digest_content)
                except Exception:
                    pass
                break

    return templates.TemplateResponse(
        request,
        "signal_detail.html",
        {"signal": signal, "runs": runs, "user": current_user, "latest_digest": latest_digest},
    )


@router.get("/partials/create-modal", response_class=HTMLResponse)
async def create_modal_partial(request: Request, current_user: User = Depends(get_current_user)):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.templates_config import templates
    return templates.TemplateResponse(
        request,
        "partials/create_modal.html",
        {"user": current_user},
    )
