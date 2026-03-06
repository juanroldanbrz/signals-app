from pydantic import BaseModel


class FlightResult(BaseModel):
    origin: str
    destination: str
    date: str                    # YYYY-MM-DD departure date
    return_date: str | None = None
    price: float
    currency: str
    airline: str | None = None
    duration_minutes: int | None = None
    url: str | None = None


class SearchParams(BaseModel):
    origin: str                  # IATA code e.g. "LHR"
    destination: str             # IATA code e.g. "MAD"
    date_from: str               # YYYY-MM-DD
    date_to: str                 # YYYY-MM-DD inclusive
    return_date: str | None = None
    passengers: int = 1


class PriceCalendar(BaseModel):
    params: SearchParams
    entries: list[FlightResult]

    def cheapest(self) -> FlightResult | None:
        return min(self.entries, key=lambda f: f.price, default=None)
