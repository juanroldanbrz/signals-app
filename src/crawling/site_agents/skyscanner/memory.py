from datetime import datetime, timezone
from src.crawling.site_agents.skyscanner.types import FlightResult, SearchParams


class SkyMemory:
    def __init__(self) -> None:
        self.searches: list[SearchParams] = []
        self.results: list[FlightResult] = []
        self.cheapest_so_far: FlightResult | None = None
        self.price_history: list[dict] = []
        self.last_search_params: SearchParams | None = None

    def add_results(self, flights: list[FlightResult]) -> None:
        self.results.extend(flights)
        for f in flights:
            if self.cheapest_so_far is None or f.price < self.cheapest_so_far.price:
                self.cheapest_so_far = f

    def to_persisted(self) -> dict:
        history = self.price_history.copy()
        now = datetime.now(timezone.utc).isoformat()
        for f in self.results:
            history.append({
                "route": f"{f.origin}-{f.destination}",
                "date": f.date,
                "price": f.price,
                "currency": f.currency,
                "checked_at": now,
            })
        return {
            "price_history": history,
            "last_search_params": (
                self.searches[-1].model_dump() if self.searches else None
            ),
        }

    @classmethod
    def from_persisted(cls, data: dict) -> "SkyMemory":
        mem = cls()
        mem.price_history = data.get("price_history", [])
        raw_params = data.get("last_search_params")
        if raw_params:
            mem.last_search_params = SearchParams(**raw_params)
        return mem

    def session_snapshot(self) -> str:
        lines = []
        if self.cheapest_so_far:
            f = self.cheapest_so_far
            lines.append(
                f"Cheapest so far: {f.origin}->{f.destination} on {f.date} "
                f"= {f.price} {f.currency}"
            )
        if self.results:
            lines.append(f"Flights found this session: {len(self.results)}")
        if self.price_history:
            lines.append(f"Historical entries: {len(self.price_history)}")
        return "\n".join(lines) if lines else "No data yet."
