import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from src.services.brave import brave_search


async def test_returns_empty_list_when_no_api_key():
    results = await brave_search("AI news", api_key="")
    assert results == []


async def test_parses_results_correctly():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "web": {
            "results": [
                {"title": "AI Article", "url": "https://example.com/ai", "age": "2 days ago"},
                {"title": "No Date", "url": "https://example.com/no-date"},
            ]
        }
    }
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("src.services.brave.httpx.AsyncClient", return_value=mock_client):
        results = await brave_search("AI news", api_key="test-key")

    assert len(results) == 2
    assert results[0].title == "AI Article"
    assert results[0].url == "https://example.com/ai"
    assert results[0].date == "2 days ago"
    assert results[1].date is None


async def test_returns_empty_list_on_network_error():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))

    with patch("src.services.brave.httpx.AsyncClient", return_value=mock_client):
        results = await brave_search("AI news", api_key="test-key")

    assert results == []


async def test_returns_empty_list_on_empty_results():
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"web": {"results": []}}
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_resp)

    with patch("src.services.brave.httpx.AsyncClient", return_value=mock_client):
        results = await brave_search("AI news", api_key="test-key")

    assert results == []
