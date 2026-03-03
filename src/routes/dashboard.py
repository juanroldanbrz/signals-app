from beanie import PydanticObjectId
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()


@router.get("/app", response_class=HTMLResponse)
async def dashboard(request: Request):
    from src.templates_config import templates
    from src.models.signal import Signal
    signals = await Signal.find_all().sort("-created_at").to_list()
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"signals": signals},
    )


@router.get("/app/signals/{signal_id}", response_class=HTMLResponse)
async def signal_detail(request: Request, signal_id: PydanticObjectId):
    from src.templates_config import templates
    from src.models.signal import Signal
    from src.models.signal_run import SignalRun
    signal = await Signal.get(signal_id)
    if not signal:
        return RedirectResponse(url="/app", status_code=303)
    runs = await SignalRun.find(
        SignalRun.signal_id == signal.id
    ).sort("-ran_at").limit(50).to_list()
    return templates.TemplateResponse(
        request,
        "signal_detail.html",
        {"signal": signal, "runs": runs},
    )


@router.get("/partials/create-modal", response_class=HTMLResponse)
async def create_modal_partial(request: Request):
    from src.templates_config import templates
    return templates.TemplateResponse(
        request,
        "partials/create_modal.html",
        {},
    )
