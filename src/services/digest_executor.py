from datetime import datetime, timezone

from src.crawling.agent import crawl_text
from src.models.app_config import AppConfig
from src.models.digest import DigestContent, SourceRef
from src.models.signal import Signal
from src.services.brave import brave_search
from src.services.tracing import gemini_text


async def run_digest(signal: Signal, on_progress=None) -> dict:
    """
    Crawl signal.source_urls, optionally call Brave Search, summarise with Gemini.
    Returns dict with: status, raw_result, digest_content (JSON str | None), content (DigestContent | None).
    """
    async def emit(msg: str) -> None:
        if on_progress is not None:
            await on_progress(msg)

    sources_text: list[str] = []
    source_refs: list[SourceRef] = []

    for url in signal.source_urls:
        await emit(f"Crawling {url} ...")
        result = await crawl_text(url)
        if result.get("text"):
            sources_text.append(
                f"## {result['title'] or url}\nURL: {url}\nFetched: {result['fetched_at']}\n\n{result['text']}"
            )
            source_refs.append(SourceRef(
                title=result["title"] or url,
                url=url,
                date=result["fetched_at"][:10],
            ))
            await emit(f"✓ {url} — {len(result['text']):,} chars")
        else:
            await emit(f"⚠ Could not fetch {url}")

    if signal.search_query:
        config = await AppConfig.get_for_user(signal.user_id)
        if config.brave_api_key and config.brave_search_enabled:
            await emit(f"Searching web: {signal.search_query} ...")
            search_results = await brave_search(signal.search_query, config.brave_api_key)
            for sr in search_results:
                sources_text.append(f"## {sr.title}\nURL: {sr.url}\nDate: {sr.date or 'unknown'}")
                source_refs.append(sr)
            await emit(f"✓ Found {len(search_results)} web results")

    if not sources_text:
        return {
            "status": "error",
            "raw_result": "No content fetched from any source",
            "digest_content": None,
            "content": None,
        }

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    prompt = (
        f"Today is {today}. Summarise the following content for a quick briefing.\n"
        f"Topic: {signal.source_extraction_query or 'general summary'}\n\n"
        f"STRICT FORMAT RULES:\n"
        f"- summary: exactly 2-3 sentences. No more.\n"
        f"- key_points: exactly 2-3 bullets. Each bullet max 15 words.\n"
        f"- sources: one entry per crawled URL.\n"
        f"Do not invent facts. Include specific dates found in the content.\n\n"
        f"---\n\n" + "\n\n---\n\n".join(sources_text)
    )

    await emit("Summarising with AI ...")
    raw = await gemini_text(name="digest_summary", prompt=prompt, response_format=DigestContent)

    try:
        content = DigestContent.model_validate_json(raw)
        existing_urls = {s.url for s in content.sources}
        for ref in source_refs:
            if ref.url not in existing_urls:
                content.sources.append(ref)
    except Exception:
        content = DigestContent(
            summary=raw[:500] if raw else "No summary generated",
            key_points=[],
            sources=source_refs,
        )

    await emit("✓ Summary ready")
    return {
        "status": "ok",
        "raw_result": "digest",
        "digest_content": content.model_dump_json(),
        "content": content,
    }
