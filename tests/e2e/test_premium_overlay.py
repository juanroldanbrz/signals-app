"""
E2E: FREE user hits a bot-blocked website (Skyscanner) during digest preview
→ premium upgrade overlay appears over the modal.

Requirements:
  docker compose -f docker-compose.test.yml up -d
  pytest tests/e2e -m e2e -s
"""
import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _open_create_modal(page: Page) -> None:
    """Click the CREATE SIGNAL button on the dashboard to load the modal."""
    page.goto("/app")
    page.click("text=+ CREATE SIGNAL")
    expect(page.locator("#create-modal")).to_be_visible(timeout=5_000)


def _navigate_to_digest_predefined(page: Page) -> None:
    """Navigate through type picker → DIGEST → source picker → PREDEFINED."""
    page.click("text=DIGEST")
    expect(page.locator("#phase-digest-source")).to_be_visible(timeout=3_000)
    page.click("text=PREDEFINED SOURCES")
    expect(page.locator("#phase-digest")).not_to_have_class("hidden", timeout=3_000)


@pytest.mark.e2e
def test_skyscanner_blocked_shows_premium_overlay(page: Page):
    """
    A FREE user who selects the Skyscanner predefined source and clicks PREVIEW
    should see the premium upgrade overlay (Skyscanner blocks headless browsers).
    """
    _open_create_modal(page)
    _navigate_to_digest_predefined(page)

    # Fill in a topic query
    page.fill("#d-query", "cheapest flights from London to New York")

    # Click PREVIEW — this triggers the crawl + blocking detection
    page.click("#digest-preview-btn")

    # The premium overlay should appear (Skyscanner blocks headless crawlers).
    # Allow up to 60s for the crawl attempt to complete.
    premium_overlay = page.locator("#premium-overlay")
    expect(premium_overlay).to_be_visible(timeout=60_000)

    # Overlay must contain the upgrade CTA
    expect(premium_overlay).to_contain_text("PREMIUM REQUIRED")
    expect(premium_overlay).to_contain_text("UPGRADE TO PREMIUM")

    # The modal itself should still be present (not closed)
    expect(page.locator("#create-modal")).to_be_visible()
