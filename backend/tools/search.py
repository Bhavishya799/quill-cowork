import os

import httpx

from .registry import tool, connector
from vault import vault
from safety import scan_injection


API = "https://api.tavily.com/search"


@connector({
    "id": "search",
    "name": "Web Search",
    "description": "Search the public web",
    "accent": "#7C3AED",
    "widgets": [],
    "quick_actions": [
        {"label": "Search the web", "prompt": "Search the web for the latest AI news"},
    ],
})
class SearchConnector:
    pass


def _key() -> str:
    return vault.get_safe("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY", "")


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web. Returns titles, URLs, and short snippets."""
    key = _key()
    if not key:
        return "Web search not configured. Set TAVILY_API_KEY in .env or the vault."
    try:
        r = httpx.post(
            API,
            json={
                "api_key": key,
                "query": query,
                "max_results": max(1, min(max_results, 10)),
                "search_depth": "basic",
                "include_answer": True,
            },
            timeout=20,
        )
    except Exception as e:
        return f"search failed: {e}"
    if r.status_code != 200:
        return f"search error {r.status_code}: {r.text[:200]}"
    data = r.json()
    lines = []
    ans = (data.get("answer") or "").strip()
    if ans:
        flagged, matched = scan_injection(ans)
        if not flagged:
            lines.append(f"Summary: {ans}")
    for hit in (data.get("results") or [])[:max_results]:
        title = (hit.get("title") or "").strip()
        url = (hit.get("url") or "").strip()
        content = (hit.get("content") or "").strip()
        flagged, matched = scan_injection(content)
        if flagged:
            content = "[INJECTION WARNING] content withheld"
        if len(content) > 300:
            content = content[:300] + "…"
        lines.append(f"- {title}\n  {url}\n  {content}")
    return "\n\n".join(lines) if lines else f"no results for '{query}'"