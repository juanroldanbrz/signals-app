from datetime import date, timedelta
from pydantic import BaseModel as PydanticBaseModel
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

    # Match exploration script: wait for body to have substantial content, then settle
    try:
        await page.wait_for_function(
            "document.body.textContent.length > 5000", timeout=30_000
        )
        await emit("  page loaded, waiting for results to stabilise...")
    except Exception:
        await emit("  ⚠ page content threshold not reached")
    await page.wait_for_timeout(5_000)

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
        # Diagnostic: show page title + first 200 chars so we know what loaded
        try:
            preview = (await page.inner_text("body"))[:200].replace("\n", " ")
        except Exception:
            preview = "(could not read body)"
        await emit(f"  ⚠ 0 ticket elements — title={title!r} — preview: {preview}")
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
    page, params: SearchParams, on_progress: ProgressCallback = None
) -> PriceCalendar:
    """Search each day in the range (capped at _MAX_SCAN_DAYS). Emits per-day progress."""
    start = date.fromisoformat(params.date_from)
    end = date.fromisoformat(params.date_to)

    # Hard cap — scanning more days takes too long
    capped_end = min(end, start + timedelta(days=_MAX_SCAN_DAYS - 1))
    if capped_end < end and on_progress:
        await on_progress(f"⚠ Date range capped to {_MAX_SCAN_DAYS} days ({start} → {capped_end})")

    all_flights: list[FlightResult] = []
    current = start
    day_num = 0
    while current <= capped_end:
        day_num += 1
        total = (capped_end - start).days + 1
        day_url = _build_search_url(params.model_copy(update={
            "date_from": current.isoformat(), "date_to": current.isoformat(),
        }))
        if on_progress:
            await on_progress(f"Scanning day {day_num}/{total}: {current} → {day_url}")
        day_params = params.model_copy(update={
            "date_from": current.isoformat(),
            "date_to": current.isoformat(),
        })
        flights = await search_flights(page, day_params, on_progress=on_progress)
        if flights and on_progress:
            cheapest = min(flights, key=lambda f: f.price)
            await on_progress(f"  {current}: {len(flights)} flights, cheapest {cheapest.price} {cheapest.currency}")
        elif on_progress:
            await on_progress(f"  {current}: no flights found")
        all_flights.extend(flights)
        current += timedelta(days=1)

    return PriceCalendar(params=params, entries=all_flights)
