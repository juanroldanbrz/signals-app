from urllib.parse import urlparse

SITE_AGENTS: dict[str, type] = {}


def register(agent_cls: type) -> type:
    for domain in agent_cls.domains:
        SITE_AGENTS[domain] = agent_cls
    return agent_cls


def get_agent_for_url(url: str) -> type | None:
    host = urlparse(url).hostname or ""
    return next(
        (cls for domain, cls in SITE_AGENTS.items() if domain in host),
        None,
    )


# Auto-register all site agents
import src.crawling.site_agents.skyscanner  # noqa: F401, E402
