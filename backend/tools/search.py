import os
import httpx
from .registry import tool, connector
from vault import vault
from safety import scan_injection

API = "https://api.tavily.com/search"


@connector({
    "id": "search",
    "name": "Web Search",
    "description": "Search the public web (SearxNG local, Tavily fallback)",
    "accent": "#7C3AED",
    "widgets": [],
    "quick_actions": [
        {"label": "Search the web", "prompt": "Search the web for the latest AI news"},
    ],
})
class SearchConnector:
    pass


def _tavily_key() -> str:
    return vault.get_safe("TAVILY_API_KEY") or os.getenv("TAVILY_API_KEY", "")


def is_configured() -> bool:
    """True if either SearxNG or Tavily is available."""
    if (os.getenv("SEARXNG_URL", "") or "").strip():
        return True
    return bool(_tavily_key())


def _config_hint() -> str:
    sx = (os.getenv("SEARXNG_URL", "") or "").strip()
    if sx:
        return (f"SEARXNG_URL is set to {sx} but the instance did not respond, "
                f"and TAVILY_API_KEY is empty. Start SearxNG "
                f"(docker run -d -p 8888:8080 searxng/searxng) or set "
                f"TAVILY_API_KEY in backend/.env, then restart the server.")
    return ("Set TAVILY_API_KEY in backend/.env, or set SEARXNG_URL to a "
            "running SearxNG instance. Do NOT retry with different "
            "arguments; this is a setup issue, not a query issue.")


def search_structured(query: str, max_results: int = 5) -> dict:
    """Search and return structured results.

    Returns {"ok": bool, "backend": "searxng"|"tavily", "results": [...]}.
    Never raises.
    """
    # Try SearxNG first
    try:
        from . import searxng as _sx
        hits = _sx.search_raw(query, max_results)
        if hits:
            return {"ok": True, "backend": "searxng", "results": hits}
    except Exception:
        pass

    # Fall back to Tavily
    key = _tavily_key()
    if not key:
        return {"ok": False, "backend": "none", "results": [],
                "error": _config_hint()}
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
        return {"ok": False, "backend": "tavily", "results": [],
                "error": f"search failed: {e}"}
    if r.status_code != 200:
        return {"ok": False, "backend": "tavily", "results": [],
                "error": f"search error {r.status_code}: {r.text[:200]}"}
    data = r.json()
    hits = []
    for h in (data.get("results") or [])[:max_results]:
        content = (h.get("content") or "").strip()
        flagged, _ = scan_injection(content)
        if flagged:
            content = "[INJECTION WARNING]"
        if len(content) > 300:
            content = content[:300] + "\u2026"
        hits.append({
            "title": (h.get("title") or "").strip(),
            "url": (h.get("url") or "").strip(),
            "snippet": content,
            "engine": "tavily",
        })
    answer = (data.get("answer") or "").strip()
    result = {"ok": True, "backend": "tavily", "results": hits}
    if answer:
        result["answer"] = answer
    return result


def format_results(structured: dict) -> str:
    """Format structured results as a string for the model."""
    if not structured.get("ok"):
        return structured.get("error") or "search failed"
    lines = []
    ans = (structured.get("answer") or "").strip()
    if ans:
        lines.append(f"Summary: {ans}")
    for h in structured.get("results", []):
        lines.append(f"- {h['title']}\n  {h['url']}\n  {h['snippet']}")
    return "\n\n".join(lines) if lines else "no results"


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web. ALWAYS call this when the user asks you
    to search, google, look up, research, or find information about
    anything current, recent, or factual you cannot verify. Do NOT
    answer from memory if the user's request is phrased as a search
    instruction. Returns titles, URLs, and short snippets."""
    return format_results(search_structured(query, max_results))
