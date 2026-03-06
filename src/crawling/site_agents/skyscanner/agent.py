import json
from playwright.async_api import async_playwright
from src.crawling.browser import get_page
from src.crawling.site_agents.base import AgentResult, AgentTool, ProgressCallback
from src.crawling.site_agents.skyscanner.memory import SkyMemory
from src.crawling.site_agents.skyscanner.tools import (
    get_cheapest, scan_date_range, search_flights,
)
from src.services.tracing import gemini_text

MAX_ITERATIONS = 5


async def _is_flight_query(query: str) -> bool:
    """Return True only if the query is about finding or tracking flight prices."""
    raw = await gemini_text(
        name="sky_flight_classifier",
        prompt=(
            "Does this query ask about finding, searching, or tracking flight prices or routes? "
            "Answer only 'yes' or 'no'.\n"
            f"Query: {query}"
        ),
    )
    return raw.strip().lower().startswith("y")

_TOOLS: list[AgentTool] = [
    AgentTool(
        name="search_flights",
        description="Search Skyscanner for flights on a specific date. Returns a list of flights with prices.",
        parameters={
            "type": "object",
            "required": ["origin", "destination", "date_from", "date_to"],
            "properties": {
                "origin": {"type": "string", "description": "IATA airport code e.g. LHR"},
                "destination": {"type": "string", "description": "IATA airport code e.g. MAD"},
                "date_from": {"type": "string", "description": "Departure date YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "Same as date_from for single day"},
            },
        },
    ),
    AgentTool(
        name="scan_date_range",
        description="Search Skyscanner for flights across a range of dates. Use when user wants to find cheapest date in a window.",
        parameters={
            "type": "object",
            "required": ["origin", "destination", "date_from", "date_to"],
            "properties": {
                "origin": {"type": "string"},
                "destination": {"type": "string"},
                "date_from": {"type": "string", "description": "Start of date range YYYY-MM-DD"},
                "date_to": {"type": "string", "description": "End of date range YYYY-MM-DD"},
            },
        },
    ),
    AgentTool(
        name="done",
        description="Return the final answer when you have enough information.",
        parameters={
            "type": "object",
            "properties": {
                "value": {"type": "number", "description": "Numeric value for monitor signals (e.g. cheapest price)"},
                "summary": {"type": "string", "description": "Text summary for digest signals"},
            },
        },
    ),
]


def _tools_description() -> str:
    return "\n".join(f"- {t.name}: {t.description}" for t in _TOOLS)


class SkyAgent:
    domains = ["skyscanner.com", "skyscanner.net"]
    tools = _TOOLS

    async def run(
        self,
        query: str,
        signal_id: str,
        persisted_memory: dict,
        on_progress: ProgressCallback,
    ) -> AgentResult:
        async def emit(msg: str) -> None:
            if on_progress:
                await on_progress(msg)

        if not await _is_flight_query(query):
            return AgentResult(
                value=None,
                digest_content="Not a flight query. Skyscanner agent only handles flight price searches.",
                persisted_memory={},
            )

        memory = SkyMemory.from_persisted(persisted_memory)
        final_value: float | None = None
        final_summary: str = ""

        for iteration in range(MAX_ITERATIONS):
            await emit(f"Agent iteration {iteration + 1}/{MAX_ITERATIONS}")

            prompt = (
                f"You are a Skyscanner flight search agent. Your task: {query}\n\n"
                f"Current session state:\n{memory.session_snapshot()}\n\n"
                f"Available tools:\n{_tools_description()}\n\n"
                f"Respond with ONLY a JSON object:\n"
                f'  {{"tool": "<tool_name>", "args": {{...}}}}\n'
                f"or to finish:\n"
                f'  {{"tool": "done", "value": <number or null>, "summary": "<text>"}}\n'
            )

            raw = await gemini_text(name="sky_agent_orchestrator", prompt=prompt)

            try:
                call = json.loads(raw.strip())
            except Exception:
                await emit(f"Could not parse LLM response: {raw[:80]}")
                break

            tool_name = call.get("tool")

            if tool_name == "done":
                final_value = call.get("value")
                final_summary = call.get("summary", "")
                await emit(f"Agent done — value={final_value}")
                break

            args = call.get("args", {})
            await emit(f"Calling tool: {tool_name}({args})")

            async with async_playwright() as pw:
                browser, page = await get_page("https://www.skyscanner.com", pw)
                try:
                    if tool_name == "search_flights":
                        from src.crawling.site_agents.skyscanner.types import SearchParams
                        params = SearchParams(**args)
                        flights = await search_flights(page, params)
                        memory.add_results(flights)
                        memory.searches.append(params)
                        await emit(f"Found {len(flights)} flights")

                    elif tool_name == "scan_date_range":
                        from src.crawling.site_agents.skyscanner.types import SearchParams
                        params = SearchParams(**args)
                        cal = await scan_date_range(page, params)
                        memory.add_results(cal.entries)
                        memory.searches.append(params)
                        await emit(f"Scanned {len(cal.entries)} flights across date range")

                    else:
                        await emit(f"Unknown tool: {tool_name}")
                finally:
                    await browser.close()

        return AgentResult(
            value=final_value,
            digest_content=final_summary or None,
            persisted_memory=memory.to_persisted(),
        )
