import logging

import httpx
import resend

from src.config import settings

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


async def send_email_alert(
    to_email: str,
    signal_name: str,
    value: float | None,
    condition: str,
    signal_url: str = "",
) -> None:
    if not settings.resend_api_key:
        return
    value_str = f"{value:.2f}" if value is not None else "—"
    link_html = f'<p><a href="{signal_url}">View signal →</a></p>' if signal_url else ""
    resend.api_key = settings.resend_api_key
    resend.Emails.send({
        "from": "Signals <noreply@watchsignal.app>",
        "to": [to_email],
        "subject": f"🚨 Alert triggered: {signal_name}",
        "html": f"""
            <p><strong>Alert triggered for {signal_name}</strong></p>
            <p>Value: <strong>{value_str}</strong></p>
            <p>Condition: {condition}</p>
            {link_html}
        """,
    })
    _log.info("Email alert sent to %s for signal %s", to_email, signal_name)
