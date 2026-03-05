from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.models.user import User
from src.services.auth import get_current_user

router = APIRouter()


@router.get("/app/config", response_class=HTMLResponse)
async def config_page(request: Request, current_user: User = Depends(get_current_user)):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.templates_config import templates
    from src.models.app_config import AppConfig
    from src.models.app_event import AppEvent
    from src.models.signal import Signal, SignalStatus
    from src.services.scheduler import last_catch_up_at

    config = await AppConfig.get_for_user(current_user.id)
    events = await AppEvent.find(AppEvent.user_id == current_user.id).sort("-ran_at").limit(100).to_list()
    active_count = await Signal.find(Signal.user_id == current_user.id, Signal.status == SignalStatus.ACTIVE).count()
    paused_count = await Signal.find(Signal.user_id == current_user.id, Signal.status == SignalStatus.PAUSED).count()
    return templates.TemplateResponse(request, "config.html", {
        "config": config,
        "events": events,
        "active_count": active_count,
        "paused_count": paused_count,
        "last_catch_up_at": last_catch_up_at,
        "user": current_user,
    })


@router.post("/app/config/telegram")
async def save_telegram_config(
    current_user: User = Depends(get_current_user),
    telegram_enabled: Annotated[str, Form()] = "",
    bot_token: Annotated[str, Form()] = "",
    chat_id: Annotated[str, Form()] = "",
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.models.app_config import AppConfig
    config = await AppConfig.get_for_user(current_user.id)
    config.telegram_enabled = telegram_enabled == "on"
    config.telegram_bot_token = bot_token
    config.telegram_chat_id = chat_id
    await config.save()
    return RedirectResponse(url="/app/config", status_code=303)


@router.post("/app/config/email")
async def save_email_config(
    current_user: User = Depends(get_current_user),
    email_enabled: Annotated[str, Form()] = "",
):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.models.app_config import AppConfig
    config = await AppConfig.get_for_user(current_user.id)
    config.email_enabled = email_enabled == "on"
    await config.save()
    return RedirectResponse(url="/app/config", status_code=303)


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
