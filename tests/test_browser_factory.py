import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_get_page_blocks_heavy_resources_for_premium_domain():
    """Route handler must abort image/font/media/stylesheet requests."""
    from src.crawling.browser import _should_block

    assert _should_block("image") is True
    assert _should_block("font") is True
    assert _should_block("media") is True
    assert _should_block("stylesheet") is True
    assert _should_block("document") is False
    assert _should_block("script") is False
    assert _should_block("xhr") is False


@pytest.mark.asyncio
async def test_get_page_uses_proxy_for_premium_domain():
    """When BRIGHTDATA_WSS is set and domain is premium, use connect_over_cdp."""
    with patch("src.crawling.browser.settings") as mock_settings:
        mock_settings.brightdata_wss = "wss://fake-proxy"
        mock_settings.premium_domains = "skyscanner.com"

        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)

        mock_playwright = MagicMock()
        mock_playwright.chromium.connect_over_cdp = AsyncMock(return_value=mock_browser)
        mock_playwright.chromium.launch = AsyncMock()

        from src.crawling.browser import get_page
        browser, page = await get_page("https://www.skyscanner.com/flights", mock_playwright)

        mock_playwright.chromium.connect_over_cdp.assert_called_once_with("wss://fake-proxy")
        mock_playwright.chromium.launch.assert_not_called()
        await browser.close()


@pytest.mark.asyncio
async def test_get_page_uses_direct_for_non_premium():
    """Non-premium domain must use standard chromium.launch."""
    with patch("src.crawling.browser.settings") as mock_settings:
        mock_settings.brightdata_wss = "wss://fake-proxy"
        mock_settings.premium_domains = "skyscanner.com"

        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)

        mock_playwright = MagicMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_playwright.chromium.connect_over_cdp = AsyncMock()

        from src.crawling.browser import get_page
        browser, page = await get_page("https://example.com/page", mock_playwright)

        mock_playwright.chromium.launch.assert_called_once()
        mock_playwright.chromium.connect_over_cdp.assert_not_called()
        await browser.close()


@pytest.mark.asyncio
async def test_get_page_uses_direct_when_no_wss():
    """Even for a premium domain, fall back to direct if BRIGHTDATA_WSS is empty."""
    with patch("src.crawling.browser.settings") as mock_settings:
        mock_settings.brightdata_wss = ""
        mock_settings.premium_domains = "skyscanner.com"

        mock_browser = AsyncMock()
        mock_page = AsyncMock()
        mock_browser.new_page = AsyncMock(return_value=mock_page)

        mock_playwright = MagicMock()
        mock_playwright.chromium.launch = AsyncMock(return_value=mock_browser)
        mock_playwright.chromium.connect_over_cdp = AsyncMock()

        from src.crawling.browser import get_page
        browser, page = await get_page("https://www.skyscanner.com/flights", mock_playwright)

        mock_playwright.chromium.launch.assert_called_once()
        mock_playwright.chromium.connect_over_cdp.assert_not_called()
        await browser.close()
