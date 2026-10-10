import httpx
import re

from .registry import tool, connector
from network import check_egress
from safety import scan_injection


@connector({
    "id": "web",
    "name": "Web",
    "description": "Fetch public web pages",
    "accent": "#0EA5E9",
    "widgets": [],
    "quick_actions": [
        {"label": "Fetch a page", "prompt": "Fetch https://en.wikipedia.org/wiki/Artificial_intelligence and summarize it"},
    ],
})
class WebConnector:
    pass


# Text extraction. trafilatura handles real-world article HTML much
# better than a regex strip. Optional dependency -- if it is missing,
# we fall back to the regex.

try:
    from trafilatura import extract as _tra_extract  # type: ignore
    _HAVE_TRAFILATURA = True
except ImportError:
    _tra_extract = None
    _HAVE_TRAFILATURA = False


def _regex_extract(html: str, max_chars: int) -> str:
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html,
                  flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_chars]


def _extract_text(html: str, max_chars: int) -> str:
    """Try trafilatura, fall back to the regex. Never raises."""
    if _HAVE_TRAFILATURA and _tra_extract is not None:
        try:
            text = _tra_extract(
                html,
                include_comments=False,
                include_tables=True,
                favor_precision=True,
            )
            if text and text.strip():
                text = re.sub(r"\n{3,}", "\n\n", text).strip()
                return text[:max_chars]
        except Exception:
            pass
    return _regex_extract(html, max_chars)


@tool
def fetch_page(url: str, max_chars: int = 4000) -> str:
    """Fetch a public web page and return its visible text."""
    ok, reason = check_egress(url)
    if not ok:
        return f"blocked: {reason}"

    current = url
    r = None
    try:
        with httpx.Client(
            headers={"User-Agent": "Quill/0.2"},
            timeout=20,
            follow_redirects=False,
        ) as client:
            for _ in range(5):
                r = client.get(current)
                if r.status_code in (301, 302, 303, 307, 308):
                    loc = r.headers.get("location")
                    if not loc:
                        return "redirect with no location"
                    current = str(httpx.URL(current).join(loc))
                    ok2, reason2 = check_egress(current)
                    if not ok2:
                        return f"blocked (redirect): {reason2}"
                    continue
                break
            else:
                return "too many redirects"
    except Exception as e:
        return f"fetch failed: {e}"

    if r is None or r.status_code != 200:
        return f"HTTP {r.status_code if r else 'no response'}"

    ctype = (r.headers.get("content-type") or "").lower()
    if ctype and not (ctype.startswith("text/")
                      or "json" in ctype or "xml" in ctype or "html" in ctype):
        return f"refused: content-type is {ctype}, not text"

    text = _extract_text(r.text, max_chars)

    flagged, matched = scan_injection(text)
    if flagged:
        return f"[INJECTION WARNING] content withheld ({matched})"

    return f"from {current}:\n{text}"