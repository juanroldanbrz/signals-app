import asyncio
from datetime import date, timedelta
from pydantic import BaseModel as PydanticBaseModel
from src.crawling.browser import get_page
from src.crawling.site_agents.base import ProgressCallback
from src.crawling.site_agents.skyscanner.types import FlightResult, SearchParams, PriceCalendar
from src.services.tracing import gemini_text

_MAX_HTML_CHARS = 20_000
_MAX_SCAN_DAYS = 7


class _FlightList(PydanticBaseModel):
    flights: list[FlightResult]


def _build_search_url(params: SearchParams) -> str:
    return (
        f"https://www.skyscanner.com/transport/flights"
        f"/{params.origin.lower()}/{params.destination.lower()}"
        f"/{params.date_from.replace('-', '')}/"
        f"?adults={params.passengers}&currency=EUR"
    )


async def search_flights(
    page, params: SearchParams, on_progress: ProgressCallback = None
) -> list[FlightResult]:
    url = _build_search_url(params)

    async def emit(msg: str) -> None:
        if on_progress:
            await on_progress(msg)

    try:
        await page.goto(url, wait_until="load", timeout=45_000)
    except Exception:
        pass

    # Phase 1: HTML shell (includes __internal JSON in <script>) — fires quickly
    try:
        await page.wait_for_function(
            "document.body.textContent.length > 5000", timeout=120_000
        )
    except Exception:
        await emit("  ⚠ page content threshold not reached")

    # Phase 2: React renders flight cards after its API calls complete — can be slow
    # Use state="attached" (DOM presence only) — CSS blocking can prevent "visible" state
    try:
        await page.wait_for_selector("[data-testid='ticket']", state="attached", timeout=120_000)
        await emit("  flight results rendered")
    except Exception:
        await emit("  ⚠ ticket selector timed out (120s) — no flights rendered yet")

    # Extract [data-testid="ticket"] elements — confirmed by exploration script
    try:
        tickets: list[str] = await page.evaluate("""() =>
            Array.from(document.querySelectorAll('[data-testid="ticket"]'))
                 .map(el => el.innerText)
        """)
    except Exception:
        tickets = []

    title = ""
    try:
        title = await page.title()
    except Exception:
        pass

    if not tickets:
        # Save a screenshot so we can see what the browser actually shows
        try:
            import uuid
            from pathlib import Path
            debug_dir = Path("/tmp/signals_screenshots")
            debug_dir.mkdir(exist_ok=True)
            fname = f"sky_debug_{uuid.uuid4().hex[:8]}.png"
            await page.screenshot(path=str(debug_dir / fname), full_page=False)
            await emit(f"  ⚠ 0 ticket elements — title={title!r} — open /screenshots/{fname} to see the page")
        except Exception as e:
            await emit(f"  ⚠ 0 ticket elements — title={title!r} — screenshot failed: {e}")
        return []

    await emit(f"  found {len(tickets)} ticket elements on {title!r}")
    text = "\n---\n".join(tickets)
    text = text[:_MAX_HTML_CHARS]

    prompt = (
        f"These are flight ticket cards from Skyscanner for "
        f"{params.origin} → {params.destination} on {params.date_from}.\n"
        f"Each block separated by --- is one ticket. Extract price and airline from each.\n"
        f"Use origin={params.origin}, destination={params.destination}, date={params.date_from}.\n"
        f"Prices may appear as '106 €', '€106', '$120', '173 EUR' etc.\n"
        f"If no tickets found return an empty flights list.\n\n"
        f"TICKETS:\n{text}"
    )

    raw = await gemini_text(
        name="skyscanner_parse_flights",
        prompt=prompt,
        response_format=_FlightList,
    )
    try:
        return _FlightList.model_validate_json(raw).flights
    except Exception:
        return []


def get_cheapest(results: list[FlightResult]) -> FlightResult | None:
    return min(results, key=lambda f: f.price, default=None)


async def scan_date_range(
    playwright, params: SearchParams, on_progress: ProgressCallback = None
) -> PriceCalendar:
    """Search all days in parallel (capped at _MAX_SCAN_DAYS). Each day gets its own browser."""
    start = date.fromisoformat(params.date_from)
    end = date.fromisoformat(params.date_to)

    capped_end = min(end, start + timedelta(days=_MAX_SCAN_DAYS - 1))
    if capped_end < end and on_progress:
        await on_progress(f"⚠ Date range capped to {_MAX_SCAN_DAYS} days ({start} → {capped_end})")

    days: list[date] = []
    current = start
    while current <= capped_end:
        days.append(current)
        current += timedelta(days=1)

    total = len(days)
    if on_progress:
        await on_progress(f"Scanning {total} days in parallel…")

    async def _search_day(day: date) -> list[FlightResult]:
        day_params = params.model_copy(update={
            "date_from": day.isoformat(),
            "date_to": day.isoformat(),
        })
        if on_progress:
            await on_progress(f"  → {day}: {_build_search_url(day_params)}")
        browser, page = await get_page("https://www.skyscanner.com", playwright)
        try:
            flights = await search_flights(page, day_params, on_progress=on_progress)
        finally:
            await browser.close()
        if on_progress:
            if flights:
                cheapest = min(flights, key=lambda f: f.price)
                await on_progress(f"  ✓ {day}: {len(flights)} flights, cheapest {cheapest.price} {cheapest.currency}")
            else:
                await on_progress(f"  ✗ {day}: no flights found")
        return flights

    results = await asyncio.gather(*[_search_day(day) for day in days])
    all_flights = [f for day_flights in results for f in day_flights]
    return PriceCalendar(params=params, entries=all_flights)
