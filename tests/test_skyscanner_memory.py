import pytest
from src.crawling.site_agents.skyscanner.types import FlightResult, SearchParams
from src.crawling.site_agents.skyscanner.memory import SkyMemory


def _flight(price: float, date: str = "2026-04-01") -> FlightResult:
    return FlightResult(origin="LHR", destination="MAD", date=date,
                        price=price, currency="EUR")


def _params() -> SearchParams:
    return SearchParams(origin="LHR", destination="MAD",
                        date_from="2026-04-01", date_to="2026-04-07")


def test_memory_starts_empty():
    mem = SkyMemory()
    assert mem.searches == []
    assert mem.results == []
    assert mem.cheapest_so_far is None


def test_add_results_updates_cheapest():
    mem = SkyMemory()
    mem.add_results([_flight(120.0), _flight(89.0), _flight(105.0)])
    assert mem.cheapest_so_far.price == 89.0


def test_add_results_accumulates():
    mem = SkyMemory()
    mem.add_results([_flight(120.0)])
    mem.add_results([_flight(60.0)])
    assert len(mem.results) == 2
    assert mem.cheapest_so_far.price == 60.0


def test_to_persisted_serialises():
    mem = SkyMemory()
    mem.add_results([_flight(89.0, "2026-04-02")])
    mem.searches.append(_params())
    data = mem.to_persisted()
    assert "price_history" in data
    assert data["price_history"][0]["price"] == 89.0
    assert data["price_history"][0]["route"] == "LHR-MAD"
    assert "last_search_params" in data


def test_load_persisted_restores_history():
    stored = {
        "price_history": [{"route": "LHR-MAD", "date": "2026-04-02",
                            "price": 89.0, "checked_at": "2026-03-01T10:00:00"}],
        "last_search_params": {"origin": "LHR", "destination": "MAD",
                                "date_from": "2026-04-01", "date_to": "2026-04-07",
                                "passengers": 1},
    }
    mem = SkyMemory.from_persisted(stored)
    assert len(mem.price_history) == 1
    assert mem.price_history[0]["price"] == 89.0
    assert mem.last_search_params.origin == "LHR"


def test_session_snapshot_for_llm():
    mem = SkyMemory()
    mem.add_results([_flight(89.0, "2026-04-02")])
    snap = mem.session_snapshot()
    assert "89" in snap
    assert "LHR" in snap
