import json
from datetime import date, timedelta
from src.crawling.site_agents.skyscanner.types import FlightResult, SearchParams, PriceCalendar
from src.services.tracing import gemini_text

_MAX_HTML_CHARS = 20_000


def _build_search_url(params: SearchParams) -> str:
    return (
        f"https://www.skyscanner.com/transport/flights"
        f"/{params.origin.lower()}/{params.destination.lower()}"
        f"/{params.date_from.replace('-', '')}/"
        f"?adults={params.passengers}&currency=EUR"
    )


async def search_flights(page, params: SearchParams) -> list[FlightResult]:
    """
    Navigate to Skyscanner search URL, extract page text, ask Gemini
    to parse flight results as JSON. Returns list[FlightResult].
    """
    url = _build_search_url(params)
    try:
        await page.goto(url, wait_until="load", timeout=30_000)
    except Exception:
        pass
    await page.wait_for_timeout(2_000)

    html = await page.content()
    text = html[:_MAX_HTML_CHARS]

    prompt = (
        f"Extract all flight offers from this Skyscanner page for "
        f"{params.origin} -> {params.destination} on {params.date_from}.\n"
        f"Return a JSON array of objects with keys: "
        f"origin, destination, date (YYYY-MM-DD), price (number), "
        f"currency (string), airline (string or null), duration_minutes (int or null).\n"
        f"If no flights found return [].\n\n"
        f"PAGE CONTENT:\n{text}"
    )

    raw = await gemini_text(name="skyscanner_parse_flights", prompt=prompt)
    try:
        data = json.loads(raw.strip())
        return [FlightResult(**item) for item in data]
    except Exception:
        return []


def get_cheapest(results: list[FlightResult]) -> FlightResult | None:
    """Return the flight with the lowest price, or None if list is empty."""
    return min(results, key=lambda f: f.price, default=None)


async def scan_date_range(page, params: SearchParams) -> PriceCalendar:
    """
    Call search_flights for each day between date_from and date_to (inclusive).
    Accumulates all results into a PriceCalendar.
    """
    start = date.fromisoformat(params.date_from)
    end = date.fromisoformat(params.date_to)
    all_flights: list[FlightResult] = []

    current = start
    while current <= end:
        day_params = params.model_copy(update={
            "date_from": current.isoformat(),
            "date_to": current.isoformat(),
        })
        flights = await search_flights(page, day_params)
        all_flights.extend(flights)
        current += timedelta(days=1)

    return PriceCalendar(params=params, entries=all_flights)
