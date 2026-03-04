from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from src.models.user import User
from src.services.auth import get_current_user

router = APIRouter()


@router.get("/app/alerts", response_class=HTMLResponse)
async def alerts_feed(request: Request, current_user: User = Depends(get_current_user)):
    if isinstance(current_user, RedirectResponse):
        return current_user
    from src.templates_config import templates
    from src.models.signal_run import SignalRun
    from src.models.signal import Signal

    alert_runs = await SignalRun.find(
        SignalRun.user_id == current_user.id,
        SignalRun.alert_triggered == True,
    ).sort("-ran_at").limit(100).to_list()

    signal_ids = {run.signal_id for run in alert_runs}
    signals = {s.id: s for s in await Signal.find({"_id": {"$in": list(signal_ids)}}).to_list()}

    return templates.TemplateResponse(request, "alerts.html", {
        "alert_runs": alert_runs,
        "signals": signals,
        "user": current_user,
    })
