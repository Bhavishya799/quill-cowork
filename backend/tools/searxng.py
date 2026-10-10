"""Local web search via SearxNG. Tavily fallback handled by search.py."""
from __future__ import annotations
import os
from typing import List, Optional
import httpx
from .registry import tool, connector
from safety import scan_injection

@connector({
    "id": "searxng",
    "name": "SearxNG",
    "description": "Local metasearch (self-hosted, no API key)",
    "accent": "#4F7A5A",
    "widgets": [],
    "quick_actions": [
        {"label": "Search local", "prompt": "Search the web for the latest AI news"},
    ],
})
class SearxNGConnector:
    pass


def _base_url() -> str:
    raw = (os.getenv("SEARXNG_URL", "") or "").strip().rstrip("/")
    if not raw:
        return "http://localhost:8888"
    if not raw.startswith("http"):
        raw = "http://" + raw
    return raw


def _timeout() -> float:
    try:
        return float(os.getenv("SEARXNG_TIMEOUT", "15"))
    except ValueError:
        return 15.0


def is_enabled() -> bool:
    return bool((os.getenv("SEARXNG_URL", "") or "").strip())


def health() -> dict:
    url = _base_url()
    try:
        r = httpx.get(f"{url}/search", params={"q": "test", "format": "json"},
                      timeout=5)
        ok = r.status_code == 200
        return {"ok": ok, "url": url, "status": r.status_code,
                "error": "" if ok else r.text[:120]}
    except Exception as e:
        return {"ok": False, "url": url, "status": 0,
                "error": f"{type(e).__name__}: {e}"}


def search_raw(query: str, max_results: int = 5) -> Optional[List[dict]]:
    """Return structured results or None if unreachable. Never raises."""
    if not is_enabled():
        return None
    try:
        r = httpx.get(
            f"{_base_url()}/search",
            params={"q": query, "format": "json", "safesearch": "1", "language": "en"},
            timeout=_timeout(),
            headers={"User-Agent": "Quill/0.4"},
        )
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    hits = (data.get("results") or [])[:max(1, min(max_results, 10))]
    out = []
    for hit in hits:
        content = (hit.get("content") or "").strip()
        flagged, _ = scan_injection(content)
        if flagged:
            content = "[INJECTION WARNING]"
        if len(content) > 300:
            content = content[:300] + "\u2026"
        out.append({
            "title": (hit.get("title") or "").strip(),
            "url": (hit.get("url") or "").strip(),
            "snippet": content,
            "engine": hit.get("engine", ""),
        })
    return out or None


def try_search(query: str, max_results: int = 5) -> Optional[str]:
    hits = search_raw(query, max_results)
    if not hits:
        return None
    lines = [f"- {h['title']}\n  {h['url']}\n  {h['snippet']}" for h in hits]
    return "\n\n".join(lines)


@tool
def searxng_health() -> str:
    """Check whether the local SearxNG instance is reachable."""
    h = health()
    if h["ok"]:
        return f"ok: {h['url']}"
    if not is_enabled():
        return "SearxNG not configured. Set SEARXNG_URL in .env."
    return f"unreachable: {h['url']} ({h['error']})"
