import re
from src.crawling.js import ACCEPT_COOKIES, CLEAN_ALL, MARK_ELEMENTS, REMOVE_OVERLAYS
from src.services.tracing import gemini_vision


async def accept_cookies(page) -> bool:
    """Click a cookie consent banner if one is present. Returns True if clicked."""
    clicked = await page.evaluate(ACCEPT_COOKIES)
    if clicked:
        await page.wait_for_timeout(500)
    return bool(clicked)


async def scroll_down(page, viewports: int = 1) -> None:
    """Scroll down by N viewport heights and wait for content to settle."""
    vh = await page.evaluate("window.innerHeight")
    await page.evaluate(f"window.scrollBy(0, {vh * viewports})")
    await page.wait_for_timeout(500)


async def find_element_id(page, query: str, on_progress=None) -> str | None:
    """
    Inject numbered overlays, take a viewport screenshot, ask Gemini which
    element contains the target. Removes visual overlays before returning.
    Returns the data-signals-id value (e.g. "5") or None if not found.
    """
    async def emit(msg: str) -> None:
        if on_progress is not None:
            await on_progress(msg)

    elements = await page.evaluate(MARK_ELEMENTS)
    if not elements:
        await emit("No elements found in viewport")
        return None

    await emit(f"Found {len(elements)} elements in viewport")

    marked_screenshot = await page.screenshot(type="png")
    await page.evaluate(REMOVE_OVERLAYS)

    element_list = "\n".join(f"{e['id']}: <{e['tag']}> {e['text']}" for e in elements)
    await emit(f"Element list:\n{element_list}")

    await emit("Asking Gemini to identify target element ...")
    raw = await gemini_vision(
        name="find_element",
        image=marked_screenshot,
        prompt=(
            f"{query}\n"
            f"Which numbered element in the screenshot contains this value/information?\n"
            f"Return ONLY the element number. If none apply, return 'not found'.\n\n"
            f"Elements:\n{element_list}"
        ),
    )
    await emit(f"Gemini response: {raw.strip()[:120]}")

    normalized = raw.strip().lower()
    if "not found" in normalized:
        await emit("Gemini: target not found in this viewport")
        return None

    match = re.search(r"\d+", normalized)
    if not match:
        await emit(f"Could not parse element number from: {raw.strip()[:80]}")
        return None

    element_id = match.group()
    el_info = next((e for e in elements if str(e["id"]) == element_id), None)
    if el_info:
        await emit(f"Selected #{element_id}: <{el_info['tag']}> {el_info['text'][:80]}")

    return element_id


async def extract_as_image(page, element_id: str) -> bytes | None:
    """Screenshot a specific element cleanly (no overlays). Returns PNG bytes or None."""
    try:
        return await page.locator(f'[data-signals-id="{element_id}"]').screenshot(type="png")
    except Exception:
        return None


async def extract_as_text(page, element_id: str) -> str | None:
    """Get the inner text of a specific element. Returns stripped text or None."""
    try:
        text = await page.locator(f'[data-signals-id="{element_id}"]').inner_text()
        return text.strip() or None
    except Exception:
        return None


async def cleanup(page) -> None:
    """Remove all injected overlays and data-signals-id attributes."""
    await page.evaluate(CLEAN_ALL)
