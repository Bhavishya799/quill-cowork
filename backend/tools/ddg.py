"""DuckDuckGo search via ddgs. No key. No Docker.

ddgs is the actively maintained fork of duckduckgo_search, installed as
a dependency of websift. We call it directly instead of going through
websift's wrapper, because ddgs has a stable public API:

    from ddgs import DDGS
    with DDGS() as d:
        hits = list(d.text(query, max_results=N))
        # each hit: {"title": ..., "href": ..., "body": ...}

Failures raise DDGError with a `kind`:
  not_installed | rate_limited | timeout | network | empty | empty_query | unknown

Callers (tools/search.py) map `kind` to user-facing messages.

Env:
  DDG_REGION      optional region code (default "us-en")
  DDG_SAFESEARCH  "on" | "moderate" | "off"   (default "moderate")
"""
from __future__ import annotations

import os
import time
from typing import List, Optional

from safety import scan_injection


class DDGError(Exception):
    """Raised by search_raw() to distinguish failure causes."""

    def __init__(self, kind: str, detail: str = ""):
        self.kind = kind
        self.detail = detail
        super().__init__(f"{kind}: {detail}" if detail else kind)


def _classify(e: Exception) -> str:
    msg = str(e).lower()
    if "429" in msg or "rate" in msg or "too many" in msg:
        return "rate_limited"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "connection" in msg or "network" in msg or "resolve" in msg:
        return "network"
    return "unknown"


def is_enabled() -> bool:
    try:
        import ddgs  # noqa: F401
        return True
    except ImportError:
        return False


def _clean(text: str, cap: int = 280) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) > cap:
        text = text[:cap].rsplit(" ", 1)[0] + "\u2026"
    return text


def _normalize(hit: dict) -> dict:
    title = (hit.get("title") or "").strip()
    url = (hit.get("href") or hit.get("url") or "").strip()
    body = hit.get("body") or hit.get("snippet") or hit.get("content") or ""
    snippet = _clean(body)
    flagged, _ = scan_injection(snippet)
    if flagged:
        snippet = "[INJECTION WARNING]"
    return {"title": title, "url": url, "snippet": snippet, "engine": "duckduckgo"}


def search_raw(query: str, max_results: int = 5, retry: bool = True) -> List[dict]:
    """Search DDG. Returns list on success, raises DDGError on failure.

    Retries once on rate_limited with a 2s backoff. Pass retry=False
    for cheap diagnostic probes that should not sleep.
    """
    if not query:
        raise DDGError("empty_query")
    try:
        from ddgs import DDGS
    except ImportError as e:
        raise DDGError("not_installed", str(e))

    region = (os.getenv("DDG_REGION", "") or "").strip() or "us-en"
    safesearch = (os.getenv("DDG_SAFESEARCH", "") or "").strip() or "moderate"
    if safesearch not in ("on", "moderate", "off"):
        safesearch = "moderate"

    attempts = 2 if retry else 1
    last_exc: Optional[Exception] = None
    for i in range(attempts):
        try:
            with DDGS() as d:
                raw = list(d.text(
                    query,
                    region=region,
                    safesearch=safesearch,
                    max_results=max(1, min(int(max_results), 10)),
                ))
            if not raw:
                raise DDGError("empty")
            out = [_normalize(h) for h in raw]
            out = [h for h in out if h["url"]]
            if not out:
                raise DDGError("empty")
            return out
        except DDGError:
            raise
        except Exception as e:
            last_exc = e
            kind = _classify(e)
            if kind == "rate_limited" and i < attempts - 1:
                time.sleep(2.0)
                continue
            raise DDGError(kind, str(e))

    raise DDGError(
        _classify(last_exc) if last_exc else "unknown",
        str(last_exc) if last_exc else "",
    )


def fetch_page(url: str, max_chars: int = 4000) -> Optional[str]:
    """Fetch a URL. Tries websift, falls back to tools/web.py. Never raises."""
    try:
        import websift
        for fn_name in ("fetch", "fetch_page", "extract"):
            fn = getattr(websift, fn_name, None)
            if callable(fn):
                try:
                    r = fn(url)
                    text = (
                        r if isinstance(r, str)
                        else (
                            getattr(r, "content", "")
                            or getattr(r, "text", "")
                            or getattr(r, "markdown", "")
                        )
                    )
                    if text:
                        return str(text).strip()[:max_chars]
                except Exception:
                    continue
    except ImportError:
        pass
    try:
        from .web import fetch_page as _web_fetch
        return _web_fetch(url, max_chars=max_chars)
    except Exception:
        return None


def health() -> dict:
    if not is_enabled():
        return {
            "ok": False,
            "backend": "duckduckgo",
            "error": "ddgs not importable (pip install websift)",
        }
    try:
        search_raw("test", max_results=1, retry=False)
        return {"ok": True, "backend": "duckduckgo", "error": ""}
    except DDGError as e:
        return {
            "ok": False,
            "backend": "duckduckgo",
            "error": f"{e.kind}: {e.detail}",
        }
