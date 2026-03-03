from src.crawling.agent import crawl


async def extract_from_url(
    url: str, extraction_query: str, chart_type: str
) -> tuple[float | None, bytes | None, str]:
    return await crawl(url, extraction_query, chart_type)


async def run_signal(signal) -> dict:
    value, _, raw_result = await extract_from_url(
        url=signal.source_url,
        extraction_query=signal.source_extraction_query,
        chart_type=signal.chart_type,
    )

    if value is None:
        return {"value": None, "alert_triggered": False, "raw_result": raw_result, "status": "error"}

    return {"value": value, "alert_triggered": False, "raw_result": raw_result, "status": "ok"}
