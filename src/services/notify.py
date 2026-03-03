import logging

import httpx

_log = logging.getLogger(__name__)


async def send_telegram_alert(
    bot_token: str,
    chat_id: str,
    signal_name: str,
    value: float | None,
    condition: str,
) -> None:
    if not bot_token or not chat_id:
        return
    value_str = f"{value:.2f}" if value is not None else "—"
    text = f"🚨 ALERT: {signal_name}\nValue: {value_str}\nCondition: {condition}"
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json={"chat_id": chat_id, "text": text})
        if response.status_code >= 400:
            _log.warning("Telegram alert failed: %s %s", response.status_code, response.text[:200])
