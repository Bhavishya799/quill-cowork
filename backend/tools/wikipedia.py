import httpx
from urllib.parse import quote

from .registry import tool, connector

SUMMARY_API = "https://en.wikipedia.org/api/rest_v1/page/summary"
SEARCH_API = "https://en.wikipedia.org/w/api.php"


@connector({
    "id": "wikipedia",
    "name": "Wikipedia",
    "description": "Search and read Wikipedia articles",
    "accent": "#6B7280",
    "widgets": [],
    "quick_actions": [
        {"label": "Look something up", "prompt": "Search Wikipedia for the Fermi paradox"},
    ],
})
class WikipediaConnector:
    pass


@tool
def search_wikipedia(query: str, limit: int = 5) -> str:
    """Search Wikipedia and return the top matching article titles."""
    try:
        r = httpx.get(
            SEARCH_API,
            params={
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": max(1, min(limit, 10)),
                "format": "json",
            },
            headers={"User-Agent": "Quill/0.2"},
            timeout=15,
        )
    except Exception as e:
        return f"search failed: {e}"
    if r.status_code != 200:
        return f"HTTP {r.status_code}"
    hits = r.json().get("query", {}).get("search", [])
    if not hits:
        return f"no results for '{query}'"
    return "\n".join(f"- {h['title']}" for h in hits)


@tool
def get_wikipedia_article(title: str) -> str:
    """Fetch the plain-text summary of a Wikipedia article by exact title."""
    try:
        r = httpx.get(
            f"{SUMMARY_API}/{quote(title, safe='')}",
            headers={"User-Agent": "Quill/0.2"},
            timeout=15,
        )
    except Exception as e:
        return f"fetch failed: {e}"
    if r.status_code == 404:
        return f"no article titled '{title}'"
    if r.status_code != 200:
        return f"HTTP {r.status_code}"
    d = r.json()
    extract = (d.get("extract") or "").strip()
    if not extract:
        return f"'{d.get('title', title)}' has no summary extract."
    return f"{d.get('title', title)}\n\n{extract}"