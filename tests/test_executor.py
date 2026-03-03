import pytest
from unittest.mock import AsyncMock, patch

from src.services.executor import extract_from_url


@pytest.mark.asyncio
async def test_extract_numeric_returns_float():
    with patch("src.services.executor.crawl", AsyncMock(return_value=(67432.10, b"img.png", "67432.10"))):
        value, screenshot, _ = await extract_from_url("https://example.com", "BTC price", "line")
    assert value == 67432.10
    assert screenshot == b"img.png"


@pytest.mark.asyncio
async def test_extract_numeric_returns_none_on_failure():
    with patch("src.services.executor.crawl", AsyncMock(return_value=(None, None, "Could not extract"))):
        value, screenshot, msg = await extract_from_url("https://example.com", "BTC price", "line")
    assert value is None
    assert screenshot is None
    assert "could not extract" in msg.lower()


@pytest.mark.asyncio
async def test_extract_flag_true():
    with patch("src.services.executor.crawl", AsyncMock(return_value=(1.0, b"img.png", "true"))):
        value, _, _ = await extract_from_url("https://example.com", "Is site online?", "flag")
    assert value == 1.0


@pytest.mark.asyncio
async def test_extract_flag_false():
    with patch("src.services.executor.crawl", AsyncMock(return_value=(0.0, b"img.png", "false"))):
        value, _, _ = await extract_from_url("https://example.com", "Price above 100k?", "flag")
    assert value == 0.0


@pytest.mark.asyncio
async def test_extract_returns_none_when_element_not_found():
    with patch("src.services.executor.crawl", AsyncMock(return_value=(None, None, "Could not locate relevant element after 3 scroll attempts"))):
        value, screenshot, msg = await extract_from_url("https://example.com", "BTC price", "line")
    assert value is None
    assert screenshot is None
    assert "3 scroll attempts" in msg
