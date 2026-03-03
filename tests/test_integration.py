"""
Integration tests — hit real URLs with the actual browser agent.
Run with:  pytest -m integration -s
The -s flag shows the live console output.

Each case asserts:
  1. A numeric value was extracted.
  2. The element screenshot was captured (element was actually found).
  3. The raw element text is non-trivially short and contains at least one digit
     (so we know the agent targeted a data-bearing element, not a header/nav).
"""
from datetime import datetime

import pytest

from src.crawling.agent import crawl


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] {msg}")


def _summarise(value, screenshot, raw) -> None:
    print(f"\n{'='*60}")
    print(f"Final value : {value}")
    print(f"Raw result  : {str(raw)[:300]}")
    print(f"Screenshot  : {'yes, ' + str(len(screenshot)) + ' bytes' if screenshot else 'none'}")
    print(f"{'='*60}")


def _assert_result(value, screenshot, raw, *, min_val=0, max_val=1_000_000, label="value"):
    """Shared assertions for every integration case."""
    _summarise(value, screenshot, raw)

    assert value is not None, f"Agent returned None — raw: {raw}"
    assert isinstance(value, float), f"Expected float, got {type(value)}: {value}"
    assert value > min_val, f"{label} must be > {min_val}, got {value}"
    assert value < max_val, f"{label} suspiciously large: {value}"

    assert screenshot is not None, "No element screenshot — element was never found"

    # If text extraction succeeded, raw contains the element text.
    # "extracted from screenshot" means vision fallback was used — still acceptable.
    if raw not in ("extracted from screenshot",):
        assert any(ch.isdigit() for ch in raw), (
            f"Element text contains no digits — likely wrong element: {raw[:200]}"
        )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

@pytest.mark.integration
async def test_allkeyshop_dragon_quest_best_steam_price():
    """
    Allkeyshop price-comparison page — extract the lowest Steam price for
    Dragon Quest I & II HD-2D Remake.  Prices are typically $20–$80.
    """
    value, screenshot, raw = await crawl(
        url="https://www.allkeyshop.com/blog/en-us/buy-dragon-quest-i-ii-hd-2d-remake-cd-key-compare-prices/",
        query="What is the best (lowest) Steam price for Dragon Quest I & II HD-2D Remake?",
        chart_type="line",
        on_progress=_log,
    )

    _assert_result(value, screenshot, raw, min_val=0, max_val=500, label="Steam price")


@pytest.mark.integration
async def test_coinmarketcap_bitcoin_price():
    """
    CoinMarketCap — extract the current Bitcoin (BTC) price in USD.
    Prices are typically $10 000–$500 000.
    """
    value, screenshot, raw = await crawl(
        url="https://coinmarketcap.com/currencies/bitcoin/",
        query="What is the current Bitcoin (BTC) price in USD?",
        chart_type="line",
        on_progress=_log,
    )

    _assert_result(value, screenshot, raw, min_val=1_000, max_val=10_000_000, label="BTC price")
