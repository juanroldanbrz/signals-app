import re
from collections.abc import Callable, Awaitable
from playwright.async_api import async_playwright
from src.crawling.actions import (
    accept_cookies,
    cleanup,
    extract_as_image,
    extract_as_text,
    find_element_id,
    scroll_down,
)
from src.services.tracing import gemini_text, gemini_vision

type ProgressCallback = Callable[[str], Awaitable[None]] | None


async def _emit(msg: str, on_progress: ProgressCallback) -> None:
    if on_progress is not None:
        await on_progress(msg)


async def _parse_from_text(
    text: str, query: str, chart_type: str, on_progress: ProgressCallback
) -> float | None:
    await _emit(f"Element text:\n{text[:300]}", on_progress)

    if chart_type == "flag":
        raw = await gemini_text(
            name="parse_flag_text",
            prompt=f"Text:\n{text}\n\nQuestion: {query}\nReturn ONLY: true or false. Nothing else.",
        )
        await _emit(f"Gemini text parse → {raw.strip()[:80]}", on_progress)
        raw = raw.strip().lower()
        if "true" in raw:
            return 1.0
        if "false" in raw:
            return 0.0
        return None

    raw = await gemini_text(
        name="parse_value_text",
        prompt=(
            f"Text:\n{text}\n\n"
            f"Query: {query}\n"
            f"Return ONLY the number (e.g. 67432.10), no units, no text.\n"
            f"If the value is not present, return null."
        ),
    )
    await _emit(f"Gemini text parse → {raw.strip()[:80]}", on_progress)
    raw = raw.strip()
    if raw.lower() in ("null", "none", ""):
        return None
    match = re.search(r"\d+\.?\d*", raw.replace(",", ""))
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass
    return None


async def _parse_from_image(
    screenshot: bytes, query: str, chart_type: str, on_progress: ProgressCallback
) -> float | None:
    await _emit(f"Screenshot size: {len(screenshot):,} bytes", on_progress)

    if chart_type == "flag":
        raw = await gemini_vision(
            name="parse_flag_image",
            image=screenshot,
            prompt=f"{query}\nReturn ONLY: true or false. Nothing else.",
        )
        await _emit(f"Gemini vision parse → {raw.strip()[:80]}", on_progress)
        raw = raw.strip().lower()
        if "true" in raw:
            return 1.0
        if "false" in raw:
            return 0.0
        return None

    raw = await gemini_vision(
        name="parse_value_image",
        image=screenshot,
        prompt=(
            f"{query}\n"
            f"Return ONLY the number (e.g. 67432.10), no units, no text.\n"
            f"If you cannot find a clear numeric value, return null."
        ),
    )
    await _emit(f"Gemini vision parse → {raw.strip()[:80]}", on_progress)
    raw = raw.strip()
    if raw.lower() in ("null", "none", ""):
        return None
    match = re.search(r"\d+\.?\d*", raw.replace(",", ""))
    if match:
        try:
            return float(match.group())
        except ValueError:
            pass
    return None


async def crawl(
    url: str,
    query: str,
    chart_type: str,
    on_progress: ProgressCallback = None,
) -> tuple[float | None, bytes | None, str]:
    """
    Browser agent: navigate to URL, accept cookies, then locate the relevant
    element by injecting numbered overlays and asking Gemini to identify it.

    Tries text extraction first (cheaper), falls back to image/vision.
    Scrolls up to 3 viewport heights if the element is not found at first.

    Returns (value, element_screenshot_bytes, raw_text_or_error).
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            page = await browser.new_page()

            await _emit(f"Navigating to {url} ...", on_progress)
            try:
                await page.goto(url, wait_until="load", timeout=30000)
            except Exception:
                pass  # timeout just means the page didn't fully settle; content is usually there
            await page.wait_for_timeout(500)

            scroll_y = await page.evaluate("window.pageYOffset")
            page_h = await page.evaluate("document.body.scrollHeight")
            await _emit(f"Page loaded — scroll position {scroll_y}px / {page_h}px total", on_progress)

            await _emit("Accepting cookies ...", on_progress)
            clicked = await accept_cookies(page)
            await _emit("Cookie banner clicked" if clicked else "No cookie banner detected", on_progress)

            for attempt in range(3):
                scroll_y = await page.evaluate("window.pageYOffset")
                await _emit(
                    f"--- Attempt {attempt + 1}/3 (scroll y={scroll_y}px) ---",
                    on_progress,
                )

                try:
                    element_id = await find_element_id(page, query, on_progress=on_progress)

                    if element_id is None:
                        if attempt < 2:
                            await _emit("Scrolling down one viewport ...", on_progress)
                            await scroll_down(page)
                        continue

                    # Text extraction first — cheaper, no vision API call
                    await _emit("Extracting element text ...", on_progress)
                    raw_text = await extract_as_text(page, element_id)
                    if raw_text:
                        await _emit("Parsing text with Gemini ...", on_progress)
                        value = await _parse_from_text(raw_text, query, chart_type, on_progress)
                        if value is not None:
                            await _emit(f"✓ Extracted value: {value}", on_progress)
                            screenshot = await extract_as_image(page, element_id)
                            return value, screenshot, raw_text
                        await _emit("Text parse returned null — trying vision ...", on_progress)
                    else:
                        await _emit("No text in element — trying vision ...", on_progress)

                    # Fall back to image/vision extraction
                    await _emit("Taking element screenshot ...", on_progress)
                    screenshot = await extract_as_image(page, element_id)
                    if screenshot:
                        await _emit("Parsing screenshot with Gemini vision ...", on_progress)
                        value = await _parse_from_image(screenshot, query, chart_type, on_progress)
                        if value is not None:
                            await _emit(f"✓ Extracted value: {value}", on_progress)
                            return value, screenshot, "extracted from screenshot"

                    await _emit("Value not found at this scroll position", on_progress)
                    if attempt < 2:
                        await _emit("Scrolling down one viewport ...", on_progress)
                        await scroll_down(page)

                finally:
                    await cleanup(page)

            return None, None, "Could not extract value after 3 scroll attempts"

    except Exception as e:
        return None, None, f"Browser error: {str(e)[:200]}"
