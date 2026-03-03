import asyncio
from datetime import datetime, timedelta, timezone
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

scheduler = AsyncIOScheduler()
last_catch_up_at: datetime | None = None


def evaluate_condition(
    condition_type: str | None,
    threshold: float | None,
    value: float,
    last_value: float | None,
) -> bool:
    if condition_type == "above":
        return threshold is not None and value > threshold
    if condition_type == "below":
        return threshold is not None and value < threshold
    if condition_type == "equals":
        return threshold is not None and value == threshold
    if condition_type == "change":
        return last_value is not None and value != last_value
    return False


def _condition_description(signal) -> str:
    ct = signal.condition_type
    t = signal.condition_threshold
    if ct == "above":
        return f"above {t}"
    if ct == "below":
        return f"below {t}"
    if ct == "equals":
        return f"equals {t}"
    if ct == "change":
        return "value changed"
    return ""


async def _run_signal_job(signal_id: str):
    from src.models.signal import Signal, SignalStatus
    from src.models.signal_run import SignalRun
    from src.models.app_config import AppConfig
    from src.models.app_event import AppEvent
    from src.services.executor import run_signal
    from src.services.notify import send_telegram_alert

    signal = await Signal.get(signal_id)
    if not signal or signal.status == SignalStatus.PAUSED:
        return

    try:
        result = await run_signal(signal)
        value = result["value"]

        alert_triggered = False
        if value is not None and signal.alert_enabled:
            alert_triggered = evaluate_condition(
                signal.condition_type,
                signal.condition_threshold,
                value,
                signal.last_value,
            )

        run = SignalRun(
            signal_id=signal.id,
            value=value,
            alert_triggered=alert_triggered,
            raw_result=result["raw_result"],
            status=result["status"],
        )
        await run.insert()

        signal.last_run_at = datetime.now(timezone.utc)
        signal.last_value = value
        signal.alert_triggered = alert_triggered

        if result["status"] == "error":
            signal.consecutive_errors += 1
            if signal.consecutive_errors >= 5:
                signal.status = SignalStatus.PAUSED
        else:
            signal.consecutive_errors = 0
            signal.status = SignalStatus.ACTIVE

        if alert_triggered:
            config = await AppConfig.get_singleton()
            await send_telegram_alert(
                bot_token=config.telegram_bot_token,
                chat_id=config.telegram_chat_id,
                signal_name=signal.name,
                value=value,
                condition=_condition_description(signal),
            )

        event_status = "error" if result["status"] == "error" else "ok"
        await AppEvent(
            signal_id=signal.id,
            signal_name=signal.name,
            value=value,
            alert_triggered=alert_triggered,
            status=event_status,
            message=result.get("raw_result", "")[:200],
        ).insert()

    except Exception as e:
        signal.consecutive_errors += 1
        signal.last_run_at = datetime.now(timezone.utc)
        if signal.consecutive_errors >= 5:
            signal.status = SignalStatus.PAUSED
        try:
            await AppEvent(
                signal_id=signal.id,
                signal_name=signal.name,
                value=None,
                alert_triggered=False,
                status="error",
                message=str(e)[:200],
            ).insert()
        except Exception:
            pass

    await signal.save()


async def _catch_up_job():
    global last_catch_up_at
    from src.models.signal import Signal, SignalStatus

    last_catch_up_at = datetime.now(timezone.utc)
    now = last_catch_up_at
    signals = await Signal.find(
        Signal.status == SignalStatus.ACTIVE,
        {"$or": [{"next_run_at": None}, {"next_run_at": {"$lte": now}}]},
    ).to_list()

    for signal in signals:
        signal.next_run_at = now + timedelta(minutes=signal.interval_minutes)
        await signal.save()
        asyncio.create_task(_run_signal_job(str(signal.id)))


def start_scheduler():
    scheduler.add_job(
        _catch_up_job,
        trigger=IntervalTrigger(minutes=10),
        id="catch_up",
        replace_existing=True,
    )
    scheduler.start()
