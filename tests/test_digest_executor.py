import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from bson import ObjectId
from src.models.digest import DigestContent, SourceRef


def _make_signal(**kwargs) -> MagicMock:
    defaults = dict(
        user_id=ObjectId(),
        name="AI News",
        source_url="",
        source_extraction_query="latest AI news",
        signal_type="digest",
        source_urls=["https://example.com"],
        search_query=None,
    )
    merged = {**defaults, **kwargs}
    signal = MagicMock()
    for k, v in merged.items():
        setattr(signal, k, v)
    return signal


async def test_run_digest_success():
    from src.services.digest_executor import run_digest

    sample = DigestContent(
        summary="AI advances rapidly in 2026.",
        key_points=["GPT-5 released", "Gemini 3 released"],
        sources=[SourceRef(title="Example", url="https://example.com", date="2026-03-05")],
    )
    signal = _make_signal()

    with patch("src.services.digest_executor.crawl_text", AsyncMock(return_value={
        "text": "Some article text about AI.", "title": "AI Article",
        "url": "https://example.com", "fetched_at": "2026-03-05T10:00:00+00:00",
    })), patch("src.services.digest_executor.gemini_text", AsyncMock(
        return_value=sample.model_dump_json()
    )):
        result = await run_digest(signal)

    assert result["status"] == "ok"
    content = DigestContent.model_validate_json(result["digest_content"])
    assert content.summary == "AI advances rapidly in 2026."
    assert len(content.key_points) == 2


async def test_run_digest_no_content_returns_error():
    from src.services.digest_executor import run_digest

    signal = _make_signal()

    with patch("src.services.digest_executor.crawl_text", AsyncMock(return_value={
        "text": "", "title": "", "url": "https://example.com",
        "fetched_at": "2026-03-05T10:00:00+00:00",
    })):
        result = await run_digest(signal)

    assert result["status"] == "error"
    assert result["digest_content"] is None


async def test_run_digest_emits_progress():
    from src.services.digest_executor import run_digest

    sample = DigestContent(summary="ok", key_points=[], sources=[])
    signal = _make_signal()
    messages = []

    async def capture(msg):
        messages.append(msg)

    with patch("src.services.digest_executor.crawl_text", AsyncMock(return_value={
        "text": "Content", "title": "Page", "url": "https://example.com",
        "fetched_at": "2026-03-05T10:00:00+00:00",
    })), patch("src.services.digest_executor.gemini_text", AsyncMock(
        return_value=sample.model_dump_json()
    )):
        await run_digest(signal, on_progress=capture)

    assert any("Crawling" in m for m in messages)
    assert any("ready" in m.lower() for m in messages)


async def test_run_digest_skips_brave_when_no_key():
    from src.services.digest_executor import run_digest

    sample = DigestContent(summary="ok", key_points=[], sources=[])
    signal = _make_signal(search_query="AI news")
    brave_mock = AsyncMock(return_value=[])

    with patch("src.services.digest_executor.crawl_text", AsyncMock(return_value={
        "text": "Content", "title": "Page", "url": "https://example.com",
        "fetched_at": "2026-03-05T10:00:00+00:00",
    })), patch("src.services.digest_executor.gemini_text", AsyncMock(
        return_value=sample.model_dump_json()
    )), patch("src.services.digest_executor.settings") as mock_settings, \
       patch("src.services.digest_executor.brave_search", brave_mock):
        mock_settings.brave_search_api_key = ""
        await run_digest(signal)

    brave_mock.assert_not_called()


async def test_run_digest_calls_brave_when_key_set():
    from src.services.digest_executor import run_digest

    sample = DigestContent(summary="ok", key_points=[], sources=[])
    signal = _make_signal(search_query="AI news")

    brave_results = [SourceRef(title="Web Result", url="https://web.com", date="2026-03-05")]
    brave_mock = AsyncMock(return_value=brave_results)

    with patch("src.services.digest_executor.crawl_text", AsyncMock(return_value={
        "text": "Content", "title": "Page", "url": "https://example.com",
        "fetched_at": "2026-03-05T10:00:00+00:00",
    })), patch("src.services.digest_executor.gemini_text", AsyncMock(
        return_value=sample.model_dump_json()
    )), patch("src.services.digest_executor.settings") as mock_settings, \
       patch("src.services.digest_executor.brave_search", brave_mock):
        mock_settings.brave_search_api_key = "test-key"
        await run_digest(signal)

    brave_mock.assert_called_once_with("AI news", "test-key")


async def test_run_digest_routes_to_site_agent_for_premium_domain():
    """When source_url matches a registered site agent, use the agent not crawl_text."""
    from src.services.digest_executor import run_digest
    from src.crawling.site_agents.base import AgentResult

    signal = _make_signal(
        source_urls=["https://www.skyscanner.com/flights/lhr/mad/"],
        agent_memory={},
    )
    agent_result = AgentResult(
        value=None,
        digest_content="Flights from LHR to MAD from €89",
        persisted_memory={"price_history": []},
    )

    mock_agent_cls = MagicMock()
    mock_agent_instance = MagicMock()
    mock_agent_instance.run = AsyncMock(return_value=agent_result)
    mock_agent_cls.return_value = mock_agent_instance

    with patch("src.services.digest_executor.get_agent_for_url",
               return_value=mock_agent_cls), \
         patch("src.services.digest_executor.crawl_text", AsyncMock()) as mock_crawl, \
         patch("src.services.digest_executor.gemini_text",
               AsyncMock(return_value='{"summary":"ok","key_points":[],"sources":[]}')):
        await run_digest(signal)

    mock_crawl.assert_not_called()
    mock_agent_instance.run.assert_called_once()
