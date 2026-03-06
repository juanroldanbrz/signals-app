from src.crawling.agent import crawl
from src.crawling.site_agents import get_agent_for_url


async def extract_from_url(
    url: str, extraction_query: str, chart_type: str
) -> tuple[float | None, bytes | None, str, str]:
    return await crawl(url, extraction_query, chart_type)


async def run_signal(signal) -> dict:
    agent_cls = get_agent_for_url(signal.source_url)
    if agent_cls:
        agent_result = await agent_cls().run(
            query=signal.source_extraction_query,
            signal_id=str(signal.id),
            persisted_memory=signal.agent_memory or {},
            on_progress=None,
        )
        signal.agent_memory = agent_result.persisted_memory
        await signal.save()
        value = agent_result.value
        if value is None:
            return {"value": None, "alert_triggered": False, "raw_result": "", "status": "error"}
        return {"value": value, "alert_triggered": False, "raw_result": "", "status": "ok"}

    value, _, raw_result, _ = await extract_from_url(
        url=signal.source_url,
        extraction_query=signal.source_extraction_query,
        chart_type=signal.chart_type,
    )

    if value is None:
        return {"value": None, "alert_triggered": False, "raw_result": raw_result, "status": "error"}

    return {"value": value, "alert_triggered": False, "raw_result": raw_result, "status": "ok"}
