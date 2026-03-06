"""
E2E tests for the signal creation modal — navigation, plan restrictions, and live crawls.

Fast tests (navigation only):  pytest tests/e2e -m e2e -k "not live" -s -v
All tests including live crawls: pytest tests/e2e -m e2e -s -v

Requires:
  docker compose -f docker-compose.test.yml up -d
  LLM_API_KEY set in .env for live crawl tests
"""
import os

import pymongo
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

# Live tests require a real LLM key — not the stub "test-key" from conftest
_LLM_KEY_AVAILABLE = bool(
    os.environ.get("LLM_API_KEY") and os.environ.get("LLM_API_KEY") != "test-key"
)
_BRAVE_KEY_AVAILABLE = bool(os.environ.get("BRAVE_SEARCH_API_KEY"))

needs_llm = pytest.mark.skipif(not _LLM_KEY_AVAILABLE, reason="LLM_API_KEY not set")
needs_brave = pytest.mark.skipif(not _BRAVE_KEY_AVAILABLE, reason="BRAVE_SEARCH_API_KEY not set")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_signals():
    """Wipe signals collection before every test so signal count is predictable."""
    from tests.e2e.conftest import TEST_MONGO_URI, TEST_MONGO_DB
    client = pymongo.MongoClient(TEST_MONGO_URI)
    client[TEST_MONGO_DB].signals.delete_many({})
    client.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def open_modal(page: Page) -> None:
    page.goto("/app")
    page.locator("button:has-text('NEW SIGNAL'), button:has-text('CREATE SIGNAL')").first.click()
    expect(page.locator("#create-modal")).to_be_visible(timeout=5_000)


def go_monitor(page: Page) -> None:
    page.locator("#phase-type-picker").get_by_text("MONITOR").click()
    expect(page.locator("#phase-monitor")).to_be_visible(timeout=3_000)


def go_digest(page: Page) -> None:
    page.locator("#phase-type-picker").get_by_text("DIGEST").click()
    expect(page.locator("#phase-digest-source")).to_be_visible(timeout=3_000)


def go_digest_source(page: Page, source: str) -> None:
    """source: 'MY URLS' | 'SEARCH ONLINE' | 'PREDEFINED SOURCES'"""
    go_digest(page)
    page.locator("#phase-digest-source").get_by_text(source).click()
    expect(page.locator("#phase-digest")).to_be_visible(timeout=3_000)


# ── Modal lifecycle ───────────────────────────────────────────────────────────

def test_modal_opens_with_type_picker(page: Page):
    open_modal(page)
    expect(page.locator("#phase-type-picker")).to_be_visible()
    expect(page.locator("#phase-type-picker")).to_contain_text("MONITOR")
    expect(page.locator("#phase-type-picker")).to_contain_text("DIGEST")


def test_modal_closes_with_x_button(page: Page):
    open_modal(page)
    page.locator("#create-modal").get_by_text("×").click()
    expect(page.locator("#create-modal")).to_have_count(0, timeout=3_000)


def test_modal_closes_clicking_backdrop(page: Page):
    open_modal(page)
    # Click the outer overlay (not the card)
    page.locator("#create-modal").click(position={"x": 10, "y": 10})
    expect(page.locator("#create-modal")).to_have_count(0, timeout=3_000)


# ── Monitor flow ──────────────────────────────────────────────────────────────

def test_monitor_form_shown_after_clicking_monitor(page: Page):
    open_modal(page)
    go_monitor(page)
    expect(page.locator("#f-name")).to_be_visible()
    expect(page.locator("#f-url")).to_be_visible()
    expect(page.locator("#f-query")).to_be_visible()
    # Chart type radios present
    expect(page.locator("input[name='chart-type'][value='line']")).to_be_visible()
    expect(page.locator("input[name='chart-type'][value='bar']")).to_be_visible()
    expect(page.locator("input[name='chart-type'][value='flag']")).to_be_visible()


def test_monitor_back_returns_to_type_picker(page: Page):
    open_modal(page)
    go_monitor(page)
    page.locator("#phase-monitor").get_by_text("← BACK").click()
    expect(page.locator("#phase-type-picker")).to_be_visible()
    expect(page.locator("#phase-monitor")).not_to_be_visible()


def test_monitor_dry_run_requires_url_and_query(page: Page):
    open_modal(page)
    go_monitor(page)
    # Click DRY RUN without filling anything
    page.click("#dry-run-btn")
    expect(page.locator("#dry-run-error")).to_be_visible()
    expect(page.locator("#dry-run-error")).to_contain_text("required")


def test_free_user_monitor_interval_locked_to_24h(page: Page):
    open_modal(page)
    go_monitor(page)
    # Select element should NOT exist — replaced by a locked display
    expect(page.locator("#f-interval[disabled], input#f-interval[type='hidden']")).to_have_count(1)
    expect(page.locator("#phase-monitor")).to_contain_text("24h")
    expect(page.locator("#phase-monitor")).to_contain_text("Upgrade")


# ── Digest source picker ──────────────────────────────────────────────────────

def test_digest_source_picker_shown_after_clicking_digest(page: Page):
    open_modal(page)
    go_digest(page)
    expect(page.locator("#phase-digest-source")).to_be_visible()
    expect(page.locator("#phase-digest-source")).to_contain_text("MY URLS")
    expect(page.locator("#phase-digest-source")).to_contain_text("SEARCH ONLINE")
    expect(page.locator("#phase-digest-source")).to_contain_text("PREDEFINED SOURCES")


def test_digest_source_picker_back_returns_to_type_picker(page: Page):
    open_modal(page)
    go_digest(page)
    page.locator("#phase-digest-source").get_by_text("← BACK").click()
    expect(page.locator("#phase-type-picker")).to_be_visible()
    expect(page.locator("#phase-digest-source")).not_to_be_visible()


# ── Digest: MY URLS ───────────────────────────────────────────────────────────

def test_digest_my_urls_shows_url_input(page: Page):
    open_modal(page)
    go_digest_source(page, "MY URLS")
    expect(page.locator("#d-source-urls-section")).to_be_visible()
    expect(page.locator("[data-url-input]")).to_have_count(1)


def test_digest_my_urls_can_add_and_remove_rows(page: Page):
    open_modal(page)
    go_digest_source(page, "MY URLS")
    # Add a row
    page.click("button:has-text('+ ADD URL')")
    expect(page.locator("[data-url-input]")).to_have_count(2)
    # Remove it
    page.locator("#d-url-list .flex").nth(1).get_by_text("✕").click()
    expect(page.locator("[data-url-input]")).to_have_count(1)
    # Can remove the last row too (no minimum)
    page.locator("#d-url-list .flex").first.get_by_text("✕").click()
    expect(page.locator("[data-url-input]")).to_have_count(0)


def test_digest_my_urls_back_returns_to_source_picker(page: Page):
    open_modal(page)
    go_digest_source(page, "MY URLS")
    page.locator("#phase-digest").get_by_text("← BACK").click()
    expect(page.locator("#phase-digest-source")).to_be_visible()
    expect(page.locator("#phase-digest")).not_to_be_visible()


# ── Digest: SEARCH ONLINE ─────────────────────────────────────────────────────

def test_digest_search_online_shows_hint(page: Page):
    open_modal(page)
    go_digest_source(page, "SEARCH ONLINE")
    expect(page.locator("#d-source-search-section")).to_be_visible()
    expect(page.locator("#d-source-search-section")).to_contain_text("searched using your topic")
    # URL inputs should NOT be visible
    expect(page.locator("#d-source-urls-section")).not_to_be_visible()


# ── Digest: PREDEFINED ────────────────────────────────────────────────────────

def test_digest_predefined_shows_skyscanner_card(page: Page):
    open_modal(page)
    go_digest_source(page, "PREDEFINED SOURCES")
    expect(page.locator("#d-source-predefined-section")).to_be_visible()
    expect(page.locator("#d-source-predefined-section")).to_contain_text("SKYSCANNER")
    expect(page.locator("#d-source-predefined-section")).to_contain_text("skyscanner.com")


# ── FREE plan restrictions ────────────────────────────────────────────────────

def test_free_user_digest_interval_locked_to_24h(page: Page):
    open_modal(page)
    go_digest_source(page, "SEARCH ONLINE")
    expect(page.locator("#phase-digest")).to_contain_text("24h")
    expect(page.locator("#phase-digest")).to_contain_text("Upgrade")


def test_free_user_new_signal_button_disabled_when_limit_reached(page: Page, test_user):
    """FREE users can only have 1 signal — button becomes disabled after that."""
    from tests.e2e.conftest import TEST_MONGO_URI, TEST_MONGO_DB
    from bson import ObjectId
    from datetime import datetime, timezone

    # Insert a fake signal owned by the test user
    client = pymongo.MongoClient(TEST_MONGO_URI)
    db = client[TEST_MONGO_DB]
    user_doc = db.users.find_one({"email": test_user["email"]})
    db.signals.insert_one({
        "user_id": user_doc["_id"],
        "name": "Dummy signal",
        "signal_type": "monitor",
        "status": "active",
        "source_url": "https://example.com",
        "source_extraction_query": "test",
        "source_urls": [],
        "search_query": None,
        "interval_minutes": 1440,
        "created_at": datetime.now(timezone.utc),
    })
    client.close()

    page.goto("/app")
    page.wait_for_load_state("networkidle")
    # Button should be disabled
    btn = page.locator("button:has-text('NEW SIGNAL')")
    expect(btn).to_be_disabled()


# ── Live crawl tests (need real LLM key) ─────────────────────────────────────

@needs_llm
def test_monitor_dry_run_coinmarketcap_bitcoin(page: Page):
    """
    Full monitor dry-run flow via UI: CoinMarketCap BTC price.
    Asserts the preview card flips in with a numeric value.
    """
    open_modal(page)
    go_monitor(page)

    page.fill("#f-name", "BTC Price")
    page.fill("#f-url", "https://coinmarketcap.com/currencies/bitcoin/")
    page.fill("#f-query", "current Bitcoin BTC price in USD")

    page.click("#dry-run-btn")

    # Console should appear and show progress
    expect(page.locator("#dry-run-console")).to_be_visible(timeout=5_000)

    # Wait for the flip to preview (value extracted) — allow up to 90s
    expect(page.locator("#preview-value")).to_be_visible(timeout=90_000)
    value_text = page.locator("#preview-value").inner_text()
    assert any(ch.isdigit() for ch in value_text), f"Expected a number in preview value, got: {value_text!r}"


@needs_llm
def test_monitor_dry_run_allkeyshop_game_price(page: Page):
    """
    Full monitor dry-run flow: Allkeyshop Steam game price.
    Replaces the integration test for allkeyshop with a real UI flow.
    """
    open_modal(page)
    go_monitor(page)

    page.fill("#f-name", "Dragon Quest Price")
    page.fill("#f-url", "https://www.allkeyshop.com/blog/en-us/buy-dragon-quest-i-ii-hd-2d-remake-cd-key-compare-prices/")
    page.fill("#f-query", "lowest Steam price for Dragon Quest I & II HD-2D Remake")

    page.click("#dry-run-btn")

    expect(page.locator("#dry-run-console")).to_be_visible(timeout=5_000)
    expect(page.locator("#preview-value")).to_be_visible(timeout=90_000)
    value_text = page.locator("#preview-value").inner_text()
    assert any(ch.isdigit() for ch in value_text), f"Expected a number in preview value, got: {value_text!r}"


@needs_llm
@needs_brave
def test_digest_search_online_returns_key_points(page: Page):
    """
    Full digest SEARCH ONLINE flow: topic → Brave search → Gemini summary.
    Asserts the preview back-face shows key points.
    """
    open_modal(page)
    go_digest_source(page, "SEARCH ONLINE")

    page.fill("#d-name", "AI News")
    page.fill("#d-query", "latest artificial intelligence research breakthroughs")

    page.click("#digest-preview-btn")

    expect(page.locator("#digest-console")).to_be_visible(timeout=5_000)
    # Wait for the flip to the digest back face
    expect(page.locator("#digest-preview-summary")).to_be_visible(timeout=90_000)
    summary = page.locator("#digest-preview-summary").inner_text()
    assert len(summary) > 20, f"Summary too short: {summary!r}"
