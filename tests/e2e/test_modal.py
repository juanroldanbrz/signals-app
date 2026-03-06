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
_BRIGHTDATA_AVAILABLE = bool(os.environ.get("BRIGHTDATA_WSS"))

needs_llm = pytest.mark.skipif(not _LLM_KEY_AVAILABLE, reason="LLM_API_KEY not set")
needs_brave = pytest.mark.skipif(not _BRAVE_KEY_AVAILABLE, reason="BRAVE_SEARCH_API_KEY not set")
needs_brightdata = pytest.mark.skipif(not _BRIGHTDATA_AVAILABLE, reason="BRIGHTDATA_WSS not set")


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_signals():
    """Wipe signals collection before every test so signal count is predictable."""
    from tests.e2e.conftest import TEST_MONGO_URI, TEST_MONGO_DB
    client = pymongo.MongoClient(TEST_MONGO_URI)
    try:
        client[TEST_MONGO_DB].signals.delete_many({})
    finally:
        client.close()


# ── Helpers ───────────────────────────────────────────────────────────────────

def open_modal(page: Page) -> None:
    page.goto("/app")
    page.locator("button:has-text('NEW SIGNAL'), button:has-text('CREATE SIGNAL')").first.click()
    expect(page.locator("#create-modal")).to_be_visible(timeout=5_000)


def go_monitor(page: Page) -> None:
    """Navigate to the URL monitor form (MONITOR → MY URL)."""
    page.locator("#phase-type-picker").get_by_text("MONITOR").click()
    expect(page.locator("#phase-monitor-source")).to_be_visible(timeout=3_000)
    page.locator("#phase-monitor-source").get_by_text("MY URL").click()
    expect(page.locator("#phase-monitor")).to_be_visible(timeout=3_000)


def go_flight_scanner(page: Page) -> None:
    """Navigate to the Flight Scanner monitor form (MONITOR → FLIGHT SCANNER)."""
    page.locator("#phase-type-picker").get_by_text("MONITOR").click()
    expect(page.locator("#phase-monitor-source")).to_be_visible(timeout=3_000)
    page.locator("#phase-monitor-source").get_by_text("FLIGHT SCANNER").click()
    expect(page.locator("#phase-sky-monitor")).to_be_visible(timeout=3_000)


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


def test_monitor_back_returns_to_source_picker(page: Page):
    open_modal(page)
    go_monitor(page)
    page.locator("#phase-monitor").get_by_text("← BACK").click()
    expect(page.locator("#phase-monitor-source")).to_be_visible()
    expect(page.locator("#phase-monitor")).not_to_be_visible()


def test_monitor_source_picker_back_returns_to_type_picker(page: Page):
    open_modal(page)
    page.locator("#phase-type-picker").get_by_text("MONITOR").click()
    expect(page.locator("#phase-monitor-source")).to_be_visible(timeout=3_000)
    page.locator("#phase-monitor-source").get_by_text("← BACK").click()
    expect(page.locator("#phase-type-picker")).to_be_visible()
    expect(page.locator("#phase-monitor-source")).not_to_be_visible()


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
    try:
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
    finally:
        client.close()

    page.goto("/app")
    page.wait_for_load_state("networkidle")
    # Button should be disabled
    btn = page.locator("button:has-text('NEW SIGNAL')")
    expect(btn).to_be_disabled()


# ── Navigation state reset (regression: stale console / flip) ─────────────────

def test_monitor_console_cleared_when_navigating_back_and_forth(page: Page):
    """Console from a failed dry-run must not persist when user goes back and re-enters monitor."""
    open_modal(page)
    go_monitor(page)
    # Trigger a validation error to cause the error element to appear
    page.click("#dry-run-btn")
    expect(page.locator("#dry-run-error")).to_be_visible()
    # Go back → source picker, then back → type picker, then re-enter monitor via MY URL
    page.locator("#phase-monitor").get_by_text("← BACK").click()
    expect(page.locator("#phase-monitor-source")).to_be_visible()
    page.locator("#phase-monitor-source").get_by_text("← BACK").click()
    expect(page.locator("#phase-type-picker")).to_be_visible()
    page.locator("#phase-type-picker").get_by_text("MONITOR").click()
    expect(page.locator("#phase-monitor-source")).to_be_visible()
    page.locator("#phase-monitor-source").get_by_text("MY URL").click()
    expect(page.locator("#phase-monitor")).to_be_visible()
    # Console should be hidden, not showing stale output
    expect(page.locator("#dry-run-console")).not_to_be_visible()


def test_digest_console_cleared_when_navigating_back(page: Page):
    """Digest console must not persist after user navigates back to source picker."""
    open_modal(page)
    go_digest_source(page, "SEARCH ONLINE")
    # Trigger preview without filling — just check we can navigate back without stale state
    # (Actual console would need a live run; we verify the element is hidden on re-entry)
    page.locator("#phase-digest").get_by_text("← BACK").click()
    expect(page.locator("#phase-digest-source")).to_be_visible()
    # Re-select SEARCH ONLINE
    page.locator("#phase-digest-source").get_by_text("SEARCH ONLINE").click()
    expect(page.locator("#phase-digest")).to_be_visible()
    expect(page.locator("#digest-console")).not_to_be_visible()


def test_digest_my_urls_rows_reset_on_re_entry(page: Page):
    """URL rows added in MY URLS must be cleared when user navigates back and re-enters."""
    open_modal(page)
    go_digest_source(page, "MY URLS")
    # Add extra rows
    page.click("button:has-text('+ ADD URL')")
    page.click("button:has-text('+ ADD URL')")
    expect(page.locator("[data-url-input]")).to_have_count(3)
    # Navigate back and re-enter MY URLS
    page.locator("#phase-digest").get_by_text("← BACK").click()
    page.locator("#phase-digest-source").get_by_text("MY URLS").click()
    # Rows should be reset to just one empty row
    expect(page.locator("[data-url-input]")).to_have_count(1)


def test_no_duplicate_modal_on_double_click(page: Page):
    """Clicking NEW SIGNAL while the modal is already open must not create a second modal."""
    open_modal(page)
    # Simulate a second click on the NEW SIGNAL button via JS (bypasses the visual overlay).
    # The hx-on::before-request guard should cancel the HTMX request.
    page.evaluate("""
        const btn = document.querySelector('[hx-get="/partials/create-modal"]');
        if (btn) btn.click();
    """)
    page.wait_for_timeout(600)
    expect(page.locator("#create-modal")).to_have_count(1)


# ── Live crawl tests (need real LLM key) ─────────────────────────────────────

@needs_llm
def test_monitor_yahoo_btc_price_extracted_and_saved(page: Page):
    """
    Full monitor flow: Yahoo Finance BTC/USD price → dry-run → save signal.
    Asserts:
    - Extracted value is numeric
    - Dashboard shows the saved signal card
    - Signal is persisted in MongoDB with correct fields
    """
    from tests.e2e.conftest import TEST_MONGO_URI, TEST_MONGO_DB

    open_modal(page)
    go_monitor(page)

    page.fill("#f-name", "BTC/USD Yahoo")
    page.fill("#f-url", "https://sg.finance.yahoo.com/quote/BTC-USD/")
    page.fill("#f-query", "current Bitcoin BTC price in USD")

    page.click("#dry-run-btn")

    expect(page.locator("#dry-run-console")).to_be_visible(timeout=5_000)
    expect(page.locator("#preview-value")).to_be_visible(timeout=90_000)

    value_text = page.locator("#preview-value").inner_text()
    assert any(ch.isdigit() for ch in value_text), f"Expected a number in preview value, got: {value_text!r}"

    # Save the signal — server returns HX-Redirect: /app so HTMX navigates away
    page.locator("#save-form button[type='submit']").click()
    page.wait_for_url("**/app**", timeout=15_000)
    page.wait_for_load_state("networkidle")

    # Signal card must appear on the dashboard
    expect(page.locator("h3:has-text('BTC/USD Yahoo')")).to_be_visible(timeout=5_000)

    # Confirm persisted correctly in MongoDB
    client = pymongo.MongoClient(TEST_MONGO_URI)
    try:
        db = client[TEST_MONGO_DB]
        doc = db.signals.find_one({"name": "BTC/USD Yahoo"})
        runs = list(db.signal_runs.find({"signal_id": doc["_id"]})) if doc else []
    finally:
        client.close()

    assert doc is not None, "Signal was not found in the database"
    assert doc["signal_type"] == "monitor"
    assert doc["source_url"] == "https://sg.finance.yahoo.com/quote/BTC-USD/"
    assert doc["source_extraction_query"] == "current Bitcoin BTC price in USD"
    assert doc["interval_minutes"] == 1440  # FREE user locked to 24h
    assert len(runs) >= 1, "Expected at least one SignalRun saved from the dry-run preview"
    assert runs[0]["value"] is not None, "Initial run value should not be None"


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


# ── Flight Scanner (monitor source picker) ────────────────────────────────────

def test_monitor_source_picker_shows_url_and_flight_scanner(page: Page):
    """Clicking MONITOR shows the source picker with MY URL and FLIGHT SCANNER."""
    open_modal(page)
    page.locator("#phase-type-picker").get_by_text("MONITOR").click()
    expect(page.locator("#phase-monitor-source")).to_be_visible(timeout=3_000)
    expect(page.locator("#phase-monitor-source")).to_contain_text("MY URL")
    expect(page.locator("#phase-monitor-source")).to_contain_text("FLIGHT SCANNER")


def test_flight_scanner_form_shown_after_clicking_flight_scanner(page: Page):
    """Clicking FLIGHT SCANNER shows the flight scanner form."""
    open_modal(page)
    go_flight_scanner(page)
    expect(page.locator("#sky-name")).to_be_visible()
    expect(page.locator("#sky-query")).to_be_visible()
    expect(page.locator("#sky-dry-run-btn")).to_be_visible()


def test_flight_scanner_back_returns_to_source_picker(page: Page):
    """Back button in flight scanner form returns to monitor source picker."""
    open_modal(page)
    go_flight_scanner(page)
    page.locator("#phase-sky-monitor").get_by_text("← BACK").click()
    expect(page.locator("#phase-monitor-source")).to_be_visible()
    expect(page.locator("#phase-sky-monitor")).not_to_be_visible()


def test_flight_scanner_dry_run_requires_query(page: Page):
    """Clicking DRY RUN without a query shows a validation error."""
    open_modal(page)
    go_flight_scanner(page)
    page.click("#sky-dry-run-btn")
    expect(page.locator("#sky-error")).to_be_visible()
    expect(page.locator("#sky-error")).to_contain_text("required")


def test_flight_scanner_console_resets_on_back_navigation(page: Page):
    """Re-entering the flight scanner form clears any previous console output."""
    open_modal(page)
    go_flight_scanner(page)
    # Manually inject some console output to simulate a previous run
    page.evaluate("document.getElementById('sky-console-output').innerHTML = '<div>old output</div>'")
    page.evaluate("document.getElementById('sky-console').classList.remove('hidden')")
    # Navigate back and re-enter
    page.locator("#phase-sky-monitor").get_by_text("← BACK").click()
    page.locator("#phase-monitor-source").get_by_text("FLIGHT SCANNER").click()
    expect(page.locator("#sky-console")).not_to_be_visible()
    assert page.locator("#sky-console-output").inner_html() == ""


@needs_brightdata
@needs_llm
def test_live_flight_scanner_dry_run_returns_price(page: Page):
    """
    Live flight scanner dry run: fill query → DRY RUN → price appears.
    Requires BRIGHTDATA_WSS and LLM_API_KEY.
    """
    open_modal(page)
    go_flight_scanner(page)

    page.fill("#sky-name", "SIN to SVQ")
    page.fill("#sky-query", "Cheapest one-way flight from Singapore to Seville between 2026-05-10 and 2026-05-15")
    page.click("#sky-dry-run-btn")

    expect(page.locator("#sky-console")).to_be_visible(timeout=5_000)
    expect(page.locator("#sky-preview-value")).to_be_visible(timeout=180_000)
    value_text = page.locator("#sky-preview-value").inner_text()
    assert any(ch.isdigit() for ch in value_text), f"Expected a price, got: {value_text!r}"
