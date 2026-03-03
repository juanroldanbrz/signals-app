import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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
