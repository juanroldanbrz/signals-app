import re
from collections.abc import Callable, Awaitable
from datetime import datetime, timezone
from bs4 import BeautifulSoup, Comment
import html2text as _html2text
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


_MAX_TEXT_CHARS = 32_000

_BLOCK_PATTERNS = [
    "just a moment",
    "attention required",
    "access denied",
    "403 forbidden",
    "please verify you are a human",
    "please complete the security check",
    "checking your browser",
    "enable javascript and cookies",
    "captcha",
    "bot traffic detected",
    "ddos protection",
    "are you a robot",
]


def _is_blocked(title: str, html: str) -> bool:
    sample = (title + " " + html[:3000]).lower()
    return any(p in sample for p in _BLOCK_PATTERNS)


def _html_to_markdown(html: str) -> str:
    """Strip boilerplate tags and convert HTML to clean markdown."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe"]):
        tag.decompose()
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()
    converter = _html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.body_width = 0
    return converter.handle(str(soup))[:_MAX_TEXT_CHARS]


async def crawl_text(url: str) -> dict:
    """
    Navigate to URL with Playwright, extract full page text as clean markdown.
    Returns dict with keys: text, title, url, fetched_at, and optionally error.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                await page.goto(url, wait_until="load", timeout=30000)
            except Exception:
                pass
            await page.wait_for_timeout(1000)
            html = await page.content()
            title = await page.title()
            await browser.close()
        blocked = _is_blocked(title, html)
        return {
            "text": "" if blocked else _html_to_markdown(html),
            "title": title,
            "url": url,
            "fetched_at": fetched_at,
            "blocked": blocked,
        }
    except Exception as e:
        return {"text": "", "title": "", "url": url, "fetched_at": fetched_at, "error": str(e)[:200]}


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
            f"Extract the best matching numeric value. Ignore currency symbols and units — return ONLY the bare number (e.g. 67432.10).\n"
            f"If no numeric value is present at all, return null."
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
) -> tuple[float | None, bytes | None, str, str]:
    """
    Browser agent: navigate to URL, accept cookies, then locate the relevant
    element by injecting numbered overlays and asking Gemini to identify it.

    Tries text extraction first (cheaper), falls back to image/vision.
    Scrolls up to 3 viewport heights if the element is not found at first.

    Returns (value, element_screenshot_bytes, raw_text_or_error, extraction_note).
    extraction_note is Gemini's one-line explanation of what it found and any caveats.
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
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

            _title = await page.title()
            _html_sample = await page.content()
            if _is_blocked(_title, _html_sample):
                await browser.close()
                return None, None, "BLOCKED", ""

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
                    result = await find_element_id(page, query, on_progress=on_progress)

                    if result is None:
                        if attempt < 2:
                            await _emit("Scrolling down one viewport ...", on_progress)
                            await scroll_down(page)
                        continue

                    element_id, note = result

                    # Text extraction first — cheaper, no vision API call
                    await _emit("Extracting element text ...", on_progress)
                    raw_text = await extract_as_text(page, element_id)
                    if raw_text:
                        await _emit("Parsing text with Gemini ...", on_progress)
                        value = await _parse_from_text(raw_text, query, chart_type, on_progress)
                        if value is not None:
                            await _emit(f"✓ Extracted value: {value}", on_progress)
                            screenshot = await extract_as_image(page, element_id)
                            return value, screenshot, raw_text, note
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
                            return value, screenshot, "extracted from screenshot", note

                    await _emit("Value not found at this scroll position", on_progress)
                    if attempt < 2:
                        await _emit("Scrolling down one viewport ...", on_progress)
                        await scroll_down(page)

                finally:
                    await cleanup(page)

            return None, None, "Could not extract value after 3 scroll attempts", ""

    except Exception as e:
        msg = str(e).split("Browser logs:")[0].strip().splitlines()[0][:200]
        return None, None, f"Browser error: {msg}", ""
