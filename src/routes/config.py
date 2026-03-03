from typing import Annotated
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

router = APIRouter()


@router.get("/app/config", response_class=HTMLResponse)
async def config_page(request: Request):
    from src.templates_config import templates
    from src.models.app_config import AppConfig
    from src.models.app_event import AppEvent
    from src.models.signal import Signal, SignalStatus
    from src.services.scheduler import last_catch_up_at

    config = await AppConfig.get_singleton()
    events = await AppEvent.find_all().sort("-ran_at").limit(100).to_list()
    active_count = await Signal.find(Signal.status == SignalStatus.ACTIVE).count()
    paused_count = await Signal.find(Signal.status == SignalStatus.PAUSED).count()
    return templates.TemplateResponse(request, "config.html", {
        "config": config,
        "events": events,
        "active_count": active_count,
        "paused_count": paused_count,
        "last_catch_up_at": last_catch_up_at,
    })


@router.post("/app/config/telegram")
async def save_telegram_config(
    bot_token: Annotated[str, Form()] = "",
    chat_id: Annotated[str, Form()] = "",
):
    from src.models.app_config import AppConfig
    config = await AppConfig.get_singleton()
    config.telegram_bot_token = bot_token
    config.telegram_chat_id = chat_id
    await config.save()
    return RedirectResponse(url="/app/config", status_code=303)
