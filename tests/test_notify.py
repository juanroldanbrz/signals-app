import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_telegram_alert_sends_message():
    with patch("httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__.return_value = mock_client
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_client.post = AsyncMock(return_value=mock_response)

        from src.services.notify import send_telegram_alert
        await send_telegram_alert(
            bot_token="testtoken",
            chat_id="123",
            signal_name="BTC Price",
            value=50000.0,
            condition="above 45000",
        )

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert "testtoken" in call_kwargs[0][0]
        assert "BTC Price" in call_kwargs[1]["json"]["text"]
        assert "50000.00" in call_kwargs[1]["json"]["text"]


@pytest.mark.asyncio
async def test_send_telegram_alert_noop_when_no_token():
    with patch("httpx.AsyncClient") as mock_client_cls:
        from src.services.notify import send_telegram_alert
        await send_telegram_alert(
            bot_token="",
            chat_id="123",
            signal_name="BTC Price",
            value=50000.0,
            condition="above 45000",
        )
        mock_client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_send_telegram_alert_noop_when_no_chat_id():
    with patch("httpx.AsyncClient") as mock_client_cls:
        from src.services.notify import send_telegram_alert
        await send_telegram_alert(
            bot_token="testtoken",
            chat_id="",
            signal_name="BTC Price",
            value=50000.0,
            condition="above 45000",
        )
        mock_client_cls.assert_not_called()


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_email_alert_sends_email():
    with patch("resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "test-id"}

        from src.services.notify import send_email_alert
        await send_email_alert(
            to_email="user@example.com",
            signal_name="BTC Price",
            value=50000.0,
            condition="above 45000",
            signal_url="https://watchsignal.app/app/signals/abc123",
        )

        mock_send.assert_called_once()
        payload = mock_send.call_args[0][0]
        assert payload["to"] == ["user@example.com"]
        assert "BTC Price" in payload["subject"]
        assert "50000.00" in payload["html"]
        assert "above 45000" in payload["html"]
        assert "watchsignal.app/app/signals/abc123" in payload["html"]


@pytest.mark.asyncio
async def test_send_email_alert_noop_when_no_api_key():
    with patch("resend.Emails.send") as mock_send:
        with patch("src.services.notify.settings") as mock_settings:
            mock_settings.resend_api_key = ""

            from src.services.notify import send_email_alert
            await send_email_alert(
                to_email="user@example.com",
                signal_name="BTC Price",
                value=50000.0,
                condition="above 45000",
            )

        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_send_email_alert_none_value():
    with patch("resend.Emails.send") as mock_send:
        mock_send.return_value = {"id": "test-id"}

        from src.services.notify import send_email_alert
        await send_email_alert(
            to_email="user@example.com",
            signal_name="Server Status",
            value=None,
            condition="value changed",
        )

        mock_send.assert_called_once()
        payload = mock_send.call_args[0][0]
        assert "—" in payload["html"]


# ---------------------------------------------------------------------------
# Integration — real Resend call
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_send_email_alert_real():
    """Send a real alert email via Resend. Requires RESEND_API_KEY in .env."""
    from src.config import settings
    from src.services.notify import send_email_alert

    assert settings.resend_api_key, "RESEND_API_KEY not set — cannot run integration test"

    await send_email_alert(
        to_email="juan.roldan.brz@gmail.com",
        signal_name="BTC Price (integration test)",
        value=99999.99,
        condition="above 90000",
        signal_url="https://watchsignal.app",
    )
