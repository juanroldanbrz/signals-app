from pydantic import BaseModel
from src.crawling.js import ACCEPT_COOKIES, CLEAN_ALL, MARK_ELEMENTS, REMOVE_OVERLAYS
from src.services.tracing import gemini_vision


class _ElementMatch(BaseModel):
    element_number: str | None = None
    note: str = ""


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


async def find_element_id(page, query: str, on_progress=None) -> tuple[str, str] | None:
    """
    Inject numbered overlays, take a viewport screenshot, ask Gemini which
    element contains the target. Removes visual overlays before returning.
    Returns (data-signals-id, explanation) or None if not found.
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
        response_format=_ElementMatch,
        prompt=(
            f"Task: {query}\n\n"
            f"Find the numbered element that best matches this task. "
            f"Be flexible: ignore currency differences (e.g. EUR vs USD), minor label mismatches, "
            f"or partial matches — focus on finding the closest relevant numeric value.\n\n"
            f"Set element_number to the number string (e.g. '5'), or null if no relevant numeric value exists.\n"
            f"Set note to a one-line explanation of what you found and any caveats "
            f"(e.g. 'Steam Global price shown in EUR €59.99 — currency differs from query').\n\n"
            f"Elements:\n{element_list}"
        ),
    )

    try:
        result = _ElementMatch.model_validate_json(raw)
    except Exception:
        await emit(f"Could not parse Gemini response: {raw[:80]}")
        return None

    if result.element_number is None:
        await emit(f"Gemini: target not found — {result.note}")
        return None

    element_id = result.element_number
    note = result.note[:200]
    el_info = next((e for e in elements if str(e["id"]) == element_id), None)
    if el_info:
        await emit(f"Selected #{element_id}: <{el_info['tag']}> {el_info['text'][:80]}")
    if note:
        await emit(f"Note: {note}")

    return element_id, note


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
