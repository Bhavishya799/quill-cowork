"""Web search: DuckDuckGo via ddgs, Tavily fallback.

DuckDuckGo needs no API key and no Docker. Tavily is optional and used
only when DuckDuckGo fails or returns nothing.

Failure causes from ddg.search_raw() (DDGError.kind) are mapped to
accurate user-facing messages:

  not_installed  → pip install websift
  rate_limited   → wait and retry, or configure Tavily
  timeout        → try again
  network        → check connection
  empty          → rephrase query
  unknown        → pass detail through

Env:
  TAVILY_API_KEY     optional fallback key
  SEARCH_MAX_CHARS   formatter budget (default 3500)
"""
import os
import time
from urllib.parse import urlparse

import httpx

from .registry import tool, connector
from vault import vault
from safety import scan_injection

API = "https://api.tavily.com/search"


@connector({
    "id": "search",
    "name": "Web Search",
    "description": "DuckDuckGo search (no key) with Tavily fallback",
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


# --- Installation check (definitive, no live query) ---
def is_installed() -> bool:
    """True if a search backend is installed. No live network call."""
    try:
        from . import ddg as _ddg
        if _ddg.is_enabled():
            return True
    except Exception:
        pass
    return bool(_tavily_key())


def is_configured() -> bool:
    """Alias for is_installed(), kept for backward compatibility."""
    return is_installed()


# --- Last observed query outcome (for /search/status hint) ---
_last_status = {"ts": 0.0, "ok": None, "kind": "", "message": ""}


def _record(ok: bool, kind: str = "", message: str = "") -> None:
    _last_status.update(ts=time.time(), ok=ok, kind=kind, message=message)


def health_detail() -> dict:
    """Install state + last observed query result."""
    installed = is_installed()
    hint = ""
    if not installed:
        hint = "Search backend not installed. Run: pip install websift"
    elif _last_status.get("ok") is False:
        hint = _last_status.get("message") or ""
    return {
        "configured": installed,
        "installed": installed,
        "hint": hint,
        "last_result_ok": _last_status.get("ok"),
        "last_result_kind": _last_status.get("kind") or "",
        "last_result_ago_s": (
            round(time.time() - _last_status["ts"], 1)
            if _last_status["ts"] else None
        ),
    }


# --- Error messages ---
def _error_message(kind: str, detail: str = "") -> str:
    messages = {
        "not_installed": (
            "DuckDuckGo search is not installed. Run: pip install websift"
        ),
        "rate_limited": (
            "DuckDuckGo rate-limited this query. Wait 5-10 seconds and "
            "try again. If this keeps happening, configure Tavily as a "
            "fallback: python vault.py set TAVILY_API_KEY <key> --sensitive"
        ),
        "timeout": "DuckDuckGo request timed out. Try again in a moment.",
        "network": (
            "Network error reaching DuckDuckGo. Check your internet "
            "connection."
        ),
        "empty": "DuckDuckGo returned no results for this query. Try rephrasing.",
        "empty_query": "Empty query.",
        "unknown": (
            f"Search failed: {detail[:200]}" if detail else "Search failed."
        ),
    }
    return messages.get(kind or "unknown", messages["unknown"])


def _config_hint() -> str:
    return _error_message("not_installed")


# --- Search ---
def search_structured(query: str, max_results: int = 5) -> dict:
    """Search and return structured results. Never raises.

    Returns {"ok": bool, "backend": str, "results": [...], "error": str,
             "error_kind": str|None}.
    """
    ddg_err_kind = None
    ddg_err_detail = ""

    try:
        from . import ddg as _ddg
        try:
            hits = _ddg.search_raw(query, max_results)
            if hits:
                _record(True)
                return {"ok": True, "backend": "duckduckgo", "results": hits}
            ddg_err_kind = "empty"
        except _ddg.DDGError as e:
            ddg_err_kind = e.kind
            ddg_err_detail = e.detail
        except Exception as e:
            ddg_err_kind = "unknown"
            ddg_err_detail = str(e)
    except ImportError as e:
        ddg_err_kind = "not_installed"
        ddg_err_detail = str(e)

    # Fall back to Tavily
    key = _tavily_key()
    if key:
        tavily_err = ""
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
            if r.status_code == 200:
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
                result = {
                    "ok": True,
                    "backend": "tavily",
                    "results": hits,
                }
                answer = (data.get("answer") or "").strip()
                if answer:
                    result["answer"] = answer
                _record(True)
                return result
            tavily_err = f"HTTP {r.status_code}: {r.text[:200]}"
        except Exception as e:
            tavily_err = f"{type(e).__name__}: {e}"

        # Both failed
        msg = _error_message(ddg_err_kind, ddg_err_detail)
        combined = f"{msg} (Tavily also failed: {tavily_err})"
        _record(False, kind=ddg_err_kind, message=combined)
        return {
            "ok": False,
            "backend": "both",
            "results": [],
            "error": combined,
            "error_kind": ddg_err_kind,
        }

    # No Tavily configured
    msg = _error_message(ddg_err_kind, ddg_err_detail)
    _record(False, kind=ddg_err_kind, message=msg)
    return {
        "ok": False,
        "backend": "duckduckgo",
        "results": [],
        "error": msg,
        "error_kind": ddg_err_kind,
    }


def _domain(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def format_results(structured: dict, max_chars: int = 0) -> str:
    """Compact numbered format for small models: [n] Title — excerpt (domain)."""
    if not structured.get("ok"):
        return structured.get("error") or "search failed"

    try:
        budget = int(max_chars or os.getenv("SEARCH_MAX_CHARS", "3500"))
    except ValueError:
        budget = 3500

    lines = []
    answer = (structured.get("answer") or "").strip()
    if answer:
        lines.append(f"Summary: {answer[:600]}")
        budget -= len(lines[-1]) + 1

    for i, h in enumerate(structured.get("results", [])[:5], 1):
        title = (h.get("title") or "").strip() or "(untitled)"
        snippet = (h.get("snippet") or "").strip()
        domain = _domain(h.get("url") or "")
        line = f"[{i}] {title}"
        if snippet:
            line += f" — {snippet[:220]}"
        if domain:
            line += f" ({domain})"
        if len(line) > budget:
            break
        lines.append(line)
        budget -= len(line) + 1
        if budget <= 0:
            break

    return "\n".join(lines) if lines else "no results"


@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web. ALWAYS call this when the user asks you
    to search, google, look up, research, or find information about
    anything current, recent, or factual you cannot verify. Do NOT
    answer from memory if the user's request is phrased as a search
    instruction. Returns numbered titles, excerpts, and domains."""
    return format_results(search_structured(query, max_results))
