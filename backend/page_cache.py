"""Deterministic page fetch + extract + chunk + cache."""
from __future__ import annotations

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Tuple

import httpx

_CACHE: Dict[str, dict] = {}
_LOCK = threading.Lock()

_STOP = set((
    "a an the and or but if then than that this these those of in on at to for "
    "from with by as is are was were be been being it its i you he she they we my "
    "your our their what which who whom whose when where why how not no do does "
    "did can could should would will shall may might must about into over under "
    "again further once here there all any both each few more most other some "
    "such only own same so too very just don now"
).split())


def _ttl() -> int:
    try:
        return max(60, int(os.getenv("DEEP_SEARCH_CACHE_TTL", "900")))
    except ValueError:
        return 900


def _timeout() -> float:
    try:
        return max(5.0, float(os.getenv("DEEP_SEARCH_TIMEOUT", "20")))
    except ValueError:
        return 20.0


def _max_chars() -> int:
    try:
        return max(2000, int(os.getenv("DEEP_SEARCH_PAGE_CHARS", "20000")))
    except ValueError:
        return 20000


def _extract(url: str) -> Tuple[str, str]:
    try:
        from ddgs import DDGS
        r = DDGS().extract(url)
        if isinstance(r, str):
            t = r
        elif isinstance(r, dict):
            t = r.get("content") or r.get("markdown") or r.get("text") or ""
        else:
            t = ""
        if t and str(t).strip():
            return str(t).strip()[:_max_chars()], "ddgs"
    except Exception:
        pass

    try:
        from network import check_egress
        ok, _why = check_egress(url)
        if not ok:
            return "", "blocked"
        with httpx.Client(timeout=_timeout(), follow_redirects=True,
                          headers={"User-Agent": "Quill/0.4"}) as c:
            r = c.get(url)
        if r.status_code != 200:
            return "", "http" + str(r.status_code)
        ctype = (r.headers.get("content-type") or "").lower()
        if ctype and not ("text" in ctype or "html" in ctype or "xml" in ctype):
            return "", "binary"
        from tools.web import _extract_text
        txt = _extract_text(r.text, _max_chars())
        if txt and txt.strip():
            return txt.strip(), "trafilatura"
    except Exception as e:
        return "", type(e).__name__

    return "", "empty"


def get(url: str, title: str = "", force: bool = False) -> dict:
    url = (url or "").strip()
    if not url:
        return {"ok": False, "url": "", "title": "", "text": "",
                "backend": "", "error": "empty url", "from_cache": False}
    now = time.time()
    with _LOCK:
        hit = _CACHE.get(url)
        if hit and not force and now - hit["ts"] < _ttl():
            out = dict(hit)
            out["from_cache"] = True
            return out
    text, backend = _extract(url)
    rec = {"ok": bool(text), "url": url, "title": title or "",
           "text": text[:_max_chars()], "backend": backend,
           "error": "" if text else (backend or "extract failed"),
           "ts": now, "from_cache": False}
    with _LOCK:
        _CACHE[url] = rec
    return rec


def get_many(items: List[dict], concurrency: int = 3) -> List[dict]:
    if not items:
        return []
    n = max(1, min(int(concurrency or 3), 5))

    def _one(it):
        return get(it.get("url", ""), it.get("title", ""))

    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(_one, items))


def chunk(text: str, size: int = 1200, overlap: int = 150) -> List[str]:
    text = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    if not text:
        return []
    if len(text) <= size:
        return [text]
    out = []
    step = max(200, size - overlap)
    for i in range(0, len(text), step):
        piece = text[i:i + size].strip()
        if piece:
            out.append(piece)
        if i + size >= len(text):
            break
    return out


def _terms(q: str) -> List[str]:
    return [w for w in re.findall(r"[a-z0-9]{3,}", (q or "").lower()) if w not in _STOP]


def rank(chunks: List[str], query: str, top: int = 2) -> List[str]:
    terms = _terms(query)
    if not terms:
        return chunks[:top]
    scored = []
    for i, ch in enumerate(chunks):
        low = ch.lower()
        score = sum(low.count(t) for t in terms)
        score += 3 * sum(1 for t in terms if t in low[:400])
        if score:
            scored.append((score, i, ch))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [c for _s, _i, c in scored[:top]] or chunks[:top]
