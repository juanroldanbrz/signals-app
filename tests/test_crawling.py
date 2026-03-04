import pytest
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

from src.crawling.agent import crawl


def _mock_pw():
    mock_page = AsyncMock()
    mock_browser = AsyncMock()
    mock_browser.new_page = AsyncMock(return_value=mock_page)
    mock_p = MagicMock()
    mock_p.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_p)
    mock_ctx.__aexit__ = AsyncMock(return_value=None)
    return mock_ctx


def _agent_patches(overrides: dict):
    base = {
        "src.crawling.agent.async_playwright": MagicMock(return_value=_mock_pw()),
        "src.crawling.agent.accept_cookies": AsyncMock(return_value=False),
        "src.crawling.agent.scroll_down": AsyncMock(),
        "src.crawling.agent.find_element_id": AsyncMock(return_value=("3", "matched element")),
        "src.crawling.agent.extract_as_text": AsyncMock(return_value=None),
        "src.crawling.agent.extract_as_image": AsyncMock(return_value=None),
        "src.crawling.agent.cleanup": AsyncMock(),
        "src.crawling.agent.gemini_text": AsyncMock(return_value="null"),
        "src.crawling.agent.gemini_vision": AsyncMock(return_value="null"),
    }
    return {**base, **overrides}


@pytest.mark.asyncio
async def test_crawl_text_extraction_succeeds():
    patches = _agent_patches({
        "src.crawling.agent.extract_as_text": AsyncMock(return_value="BTC: $67,432.10"),
        "src.crawling.agent.extract_as_image": AsyncMock(return_value=b"elem.png"),
        "src.crawling.agent.gemini_text": AsyncMock(return_value="67432.10"),
    })
    with ExitStack() as stack:
        for target, mock in patches.items():
            stack.enter_context(patch(target, mock))
        value, screenshot, raw, note = await crawl("https://example.com", "BTC price", "line")

    assert value == 67432.10
    assert screenshot == b"elem.png"
    assert "67,432" in raw


@pytest.mark.asyncio
async def test_crawl_image_fallback_when_text_parse_fails():
    patches = _agent_patches({
        "src.crawling.agent.extract_as_text": AsyncMock(return_value="some text"),
        "src.crawling.agent.extract_as_image": AsyncMock(return_value=b"elem.png"),
        "src.crawling.agent.gemini_text": AsyncMock(return_value="null"),
        "src.crawling.agent.gemini_vision": AsyncMock(return_value="67432.10"),
    })
    with ExitStack() as stack:
        for target, mock in patches.items():
            stack.enter_context(patch(target, mock))
        value, screenshot, _, note = await crawl("https://example.com", "BTC price", "line")

    assert value == 67432.10
    assert screenshot == b"elem.png"


@pytest.mark.asyncio
async def test_crawl_scrolls_and_retries():
    call_count = 0

    async def find_after_scroll(page, query, **kwargs):
        nonlocal call_count
        call_count += 1
        return ("5", "found after scroll") if call_count >= 2 else None

    patches = _agent_patches({
        "src.crawling.agent.find_element_id": find_after_scroll,
        "src.crawling.agent.extract_as_text": AsyncMock(return_value="39.33"),
        "src.crawling.agent.extract_as_image": AsyncMock(return_value=b"img.png"),
        "src.crawling.agent.gemini_text": AsyncMock(return_value="39.33"),
    })
    with ExitStack() as stack:
        for target, mock in patches.items():
            stack.enter_context(patch(target, mock))
        value, _, _, _ = await crawl("https://example.com", "price", "line")

    assert value == 39.33
    assert call_count == 2


@pytest.mark.asyncio
async def test_crawl_returns_none_after_all_attempts_fail():
    patches = _agent_patches({
        "src.crawling.agent.find_element_id": AsyncMock(return_value=None),
    })
    with ExitStack() as stack:
        for target, mock in patches.items():
            stack.enter_context(patch(target, mock))
        value, screenshot, msg, note = await crawl("https://example.com", "BTC price", "line")

    assert value is None
    assert screenshot is None
    assert "3 scroll attempts" in msg


@pytest.mark.asyncio
async def test_crawl_flag_true():
    patches = _agent_patches({
        "src.crawling.agent.extract_as_text": AsyncMock(return_value="Status: Online"),
        "src.crawling.agent.extract_as_image": AsyncMock(return_value=b"img.png"),
        "src.crawling.agent.gemini_text": AsyncMock(return_value="true"),
    })
    with ExitStack() as stack:
        for target, mock in patches.items():
            stack.enter_context(patch(target, mock))
        value, _, _, _ = await crawl("https://example.com", "Is site online?", "flag")

    assert value == 1.0


@pytest.mark.asyncio
async def test_crawl_accepts_cookies_on_first_attempt():
    accept_mock = AsyncMock(return_value=True)
    patches = _agent_patches({
        "src.crawling.agent.accept_cookies": accept_mock,
        "src.crawling.agent.extract_as_text": AsyncMock(return_value="42"),
        "src.crawling.agent.extract_as_image": AsyncMock(return_value=b"img.png"),
        "src.crawling.agent.gemini_text": AsyncMock(return_value="42"),
    })
    with ExitStack() as stack:
        for target, mock in patches.items():
            stack.enter_context(patch(target, mock))
        await crawl("https://example.com", "count", "line")

    accept_mock.assert_called_once()
