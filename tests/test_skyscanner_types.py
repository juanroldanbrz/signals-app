import pytest
from src.crawling.site_agents.skyscanner.types import (
    FlightResult, SearchParams, PriceCalendar,
)


def test_flight_result_fields():
    f = FlightResult(
        origin="LHR", destination="MAD", date="2026-04-01",
        price=89.99, currency="EUR",
    )
    assert f.origin == "LHR"
    assert f.return_date is None
    assert f.airline is None


def test_search_params_defaults():
    p = SearchParams(origin="LHR", destination="MAD",
                     date_from="2026-04-01", date_to="2026-04-07")
    assert p.passengers == 1
    assert p.return_date is None


def test_price_calendar_cheapest():
    flights = [
        FlightResult(origin="LHR", destination="MAD", date="2026-04-01", price=120.0, currency="EUR"),
        FlightResult(origin="LHR", destination="MAD", date="2026-04-02", price=89.0, currency="EUR"),
        FlightResult(origin="LHR", destination="MAD", date="2026-04-03", price=105.0, currency="EUR"),
    ]
    params = SearchParams(origin="LHR", destination="MAD",
                          date_from="2026-04-01", date_to="2026-04-03")
    cal = PriceCalendar(params=params, entries=flights)
    assert cal.cheapest().price == 89.0
    assert cal.cheapest().date == "2026-04-02"


def test_price_calendar_cheapest_empty():
    params = SearchParams(origin="LHR", destination="MAD",
                          date_from="2026-04-01", date_to="2026-04-01")
    cal = PriceCalendar(params=params, entries=[])
    assert cal.cheapest() is None
