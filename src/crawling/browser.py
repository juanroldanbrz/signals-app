from urllib.parse import urlparse
from src.config import settings

_BLOCK_RESOURCE_TYPES = {"image", "font", "media"}


def _should_block(resource_type: str) -> bool:
    return resource_type in _BLOCK_RESOURCE_TYPES


def _is_premium(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return any(d in host for d in settings.premium_domains.split(",") if d)


async def get_page(url: str, playwright) -> tuple:
    """
    Return (browser, page) for the given URL.
    - Premium domains with BRIGHTDATA_WSS set: connect via CDP proxy,
      block images/fonts/media/stylesheets.
    - All other URLs: standard headless Chromium.
    Caller is responsible for calling browser.close().
    """
    use_proxy = bool(settings.brightdata_wss) and _is_premium(url)

    if use_proxy:
        browser = await playwright.chromium.connect_over_cdp(settings.brightdata_wss)
        page = await browser.new_page()

        async def _block_route(route):
            if _should_block(route.request.resource_type):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", _block_route)
    else:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()

    return browser, page
