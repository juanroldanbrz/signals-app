import pytest
from src.crawling.site_agents import get_agent_for_url, register, SITE_AGENTS
from src.crawling.site_agents.base import AgentTool, AgentResult


def test_get_agent_for_url_returns_none_for_unknown():
    assert get_agent_for_url("https://example.com/page") is None


def test_register_maps_domains():
    class FakeAgent:
        domains = ["fake-site.com"]
        tools = []
        async def run(self, *a, **kw): ...

    register(FakeAgent)
    assert get_agent_for_url("https://fake-site.com/search") is FakeAgent
    # cleanup
    for d in FakeAgent.domains:
        SITE_AGENTS.pop(d, None)


def test_get_agent_for_url_subdomain_match():
    class FakeAgent2:
        domains = ["testsite.net"]
        tools = []
        async def run(self, *a, **kw): ...

    register(FakeAgent2)
    assert get_agent_for_url("https://www.testsite.net/flights") is FakeAgent2
    for d in FakeAgent2.domains:
        SITE_AGENTS.pop(d, None)


def test_agent_tool_model():
    tool = AgentTool(
        name="search_flights",
        description="Search for flights on given route and date",
        parameters={"type": "object", "properties": {}},
    )
    assert tool.name == "search_flights"


def test_agent_result_model():
    result = AgentResult(value=89.0, digest_content=None, persisted_memory={})
    assert result.value == 89.0
