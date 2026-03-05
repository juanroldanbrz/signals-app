import httpx
from src.models.digest import SourceRef

_BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"


async def brave_search(query: str, api_key: str, count: int = 5) -> list[SourceRef]:
    """Search Brave and return SourceRef list. Returns [] if no key or on any error."""
    if not api_key:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                _BRAVE_URL,
                headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                params={"q": query, "count": count},
            )
            resp.raise_for_status()
            data = resp.json()
            return [
                SourceRef(
                    title=item.get("title", ""),
                    url=item.get("url", ""),
                    date=item.get("age") or None,
                )
                for item in data.get("web", {}).get("results", [])
            ]
    except Exception:
        return []
