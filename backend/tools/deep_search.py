"""Deep search: read the pages, not just the snippets."""
from __future__ import annotations

import json
import os
import re
import time
from typing import List

from .registry import tool, connector
import page_cache


@connector({
    "id": "research",
    "name": "Deep Research",
    "description": "Search and actually read the top pages, returning cited findings",
    "accent": "#0F766E",
    "widgets": [],
    "quick_actions": [
        {"label": "Research a topic", "prompt": "Research the current state of solid-state batteries and cite your sources"},
    ],
})
class ResearchConnector:
    pass


_DISTILL_SYSTEM = (
    "You extract evidence from one web page. You are a filter, not a writer. "
    "Given a QUESTION and PAGE text, return only material that helps answer it. "
    "Copy exact phrases; never paraphrase numbers, names, or dates; if the page "
    "does not answer the question set relevant=false and return empty lists; "
    "never invent facts; ignore navigation, ads, cookie banners, boilerplate. "
    "Output JSON only."
)

_SCHEMA = {
    "type": "object",
    "required": ["relevant", "facts"],
    "properties": {
        "relevant": {"type": "boolean"},
        "facts": {"type": "array", "items": {"type": "string"}},
        "title": {"type": "string"},
    },
}


def _budget() -> float:
    try:
        return max(15.0, float(os.getenv("DEEP_SEARCH_BUDGET_S", "90")))
    except ValueError:
        return 90.0


def _max_chars() -> int:
    try:
        return max(800, int(os.getenv("DEEP_SEARCH_MAX_CHARS", "2500")))
    except ValueError:
        return 2500


def _max_pages() -> int:
    try:
        return max(1, min(int(os.getenv("DEEP_SEARCH_MAX_PAGES", "3")), 4))
    except ValueError:
        return 3


def _distill_enabled() -> bool:
    return os.getenv("DEEP_SEARCH_DISTILL", "1") not in ("0", "false", "False")


def _domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        h = (urlparse(url).hostname or "").lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def _clip(s: str, n: int) -> str:
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s if len(s) <= n else s[:n].rsplit(" ", 1)[0] + "..."


def _parse_json(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        pass
    if "```" in raw:
        for part in raw.split("```"):
            p = part.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            try:
                return json.loads(p)
            except Exception:
                continue
    return {}


def _sentences(text: str) -> List[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text or "")
    return [p.strip() for p in parts if len(p.strip()) > 30]


def _heuristic_facts(text: str, question: str, k: int = 3) -> List[str]:
    terms = [w for w in re.findall(r"[a-z0-9]{3,}", (question or "").lower())][:12]
    sents = _sentences(text)
    if not terms:
        return [_clip(s, 240) for s in sents[:k]]
    scored = []
    for i, s in enumerate(sents):
        low = s.lower()
        sc = sum(1 for t in terms if t in low)
        if sc:
            scored.append((sc, i, s))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [_clip(s, 240) for _sc, _i, s in scored[:k]]


def _distill(text: str, question: str, url: str, title: str) -> dict:
    text = (text or "").strip()
    if not text:
        return {"relevant": False, "facts": [], "backend": "empty"}
    fallback = _heuristic_facts(text, question, 3)
    if not _distill_enabled():
        return {"relevant": bool(fallback), "facts": fallback, "backend": "heuristic"}
    try:
        from providers import get_provider
        provider = get_provider()
        model = (os.getenv("DEEP_SEARCH_MODEL", "") or "").strip() or None
        r = provider.chat(
            messages=[
                {"role": "system", "content": _DISTILL_SYSTEM},
                {"role": "user", "content":
                    "QUESTION: " + question + "\nURL: " + url +
                    "\nTITLE: " + (title or "") + "\n\nPAGE:\n" + text[:6000]},
            ],
            tools=None,
            model=model,
            format=_SCHEMA,
        )
        d = _parse_json(r.get("content") or "")
        if isinstance(d, dict):
            facts = [str(x).strip() for x in (d.get("facts") or []) if str(x).strip()]
            if facts:
                return {"relevant": bool(d.get("relevant", True)),
                        "facts": facts[:4], "backend": "model"}
            if d.get("relevant") is False:
                return {"relevant": False, "facts": [], "backend": "model"}
    except Exception:
        pass
    return {"relevant": bool(fallback), "facts": fallback, "backend": "heuristic"}


def _build(header: str, rows: List[dict], sources: List[str]) -> str:
    out = [header, ""]
    for row in rows:
        out.append(row["head"])
        for f in row["facts"]:
            out.append("    - " + _clip(f, 220))
    if sources:
        out.append("")
        out.append("Sources:")
        out.extend(sources)
    text = "\n".join(out)
    cap = _max_chars()
    if len(text) > cap:
        text = text[:cap].rsplit("\n", 1)[0] + "\n... (truncated to fit context)"
    return text


@tool(safety={"network": True})
def deep_search(query: str, max_pages: int = 0) -> str:
    """Search the web AND read the top pages, returning cited findings.
    Use this when the user wants the sources actually checked, scanned, read,
    or compared - not just snippets."""
    q = (query or "").strip()
    if not q:
        return "deep_search failed: empty query"
    n = max_pages if max_pages else _max_pages()
    n = max(1, min(int(n), 4))
    t0 = time.time()

    try:
        from .search import search_structured
    except Exception as e:
        return "deep_search failed: " + type(e).__name__ + ": " + str(e)

    s = search_structured(q, max_results=max(5, n * 2))
    if not s.get("ok"):
        return "deep_search: search failed - " + str(s.get("error") or "no results")

    results = [r for r in (s.get("results") or []) if r.get("url")][:n]
    if not results:
        return "deep_search: no pages to read for " + repr(q)

    pages = page_cache.get_many(
        [{"url": r["url"], "title": r.get("title", "")} for r in results],
        concurrency=n,
    )

    rows = []
    sources = []
    findings = 0
    for i, (res, pg) in enumerate(zip(results, pages), 1):
        head_title = res.get("title") or pg.get("title") or _domain(res["url"]) or res["url"]
        head = "[" + str(i) + "] " + head_title + " (" + _domain(res["url"]) + ")"
        if time.time() - t0 > _budget():
            rows.append({"head": head + " - skipped (time budget)", "facts": []})
            continue
        if not pg.get("ok"):
            rows.append({"head": head + " - unreadable (" + str(pg.get("error")) + ")", "facts": []})
            sources.append("[" + str(i) + "] " + res["url"])
            continue
        chs = page_cache.rank(page_cache.chunk(pg["text"]), q, top=2)
        facts = []
        for ch in chs:
            d = _distill(ch, q, res["url"], res.get("title", ""))
            if d.get("relevant"):
                facts.extend(d["facts"])
            if len(facts) >= 4:
                break
        if facts:
            findings += len(facts)
            rows.append({"head": head, "facts": facts[:4]})
        else:
            rows.append({"head": head + " - no relevant content for this query", "facts": []})
        sources.append("[" + str(i) + "] " + res["url"])

    elapsed = time.time() - t0
    header = "Deep research: " + q + "  (" + str(len(pages)) + " pages read, " + \
             str(findings) + " findings, " + ("%.0f" % elapsed) + "s)"
    return _build(header, rows, sources)


@tool(safety={"network": True})
def read_page(url: str, question: str = "") -> str:
    """Open one URL and return only the parts that answer the question."""
    u = (url or "").strip()
    if not u:
        return "read_page failed: empty url"
    q = (question or "").strip() or "key facts and main points"
    t0 = time.time()
    pg = page_cache.get(u)
    if not pg.get("ok"):
        return "read_page: could not read " + u + " (" + str(pg.get("error")) + ")"
    chs = page_cache.rank(page_cache.chunk(pg["text"]), q, top=3)
    facts = []
    for ch in chs:
        d = _distill(ch, q, u, pg.get("title", ""))
        if d.get("relevant"):
            facts.extend(d["facts"])
        if len(facts) >= 5:
            break
    if not facts:
        return "read_page: " + u + " loaded (" + str(pg.get("backend")) + ") but nothing relevant to " + repr(q)
    head = "[1] " + (pg.get("title") or _domain(u) or u) + " (" + _domain(u) + ")"
    header = "Read: " + u + "  (" + ("%.0f" % (time.time() - t0)) + "s, " + str(pg.get("backend")) + ")"
    return _build(header, [{"head": head, "facts": facts[:5]}], ["[1] " + u])
