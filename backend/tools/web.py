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


@tool
def fetch_page(url: str, max_chars: int = 4000) -> str:
    """Fetch a public web page and return its visible text."""
    ok, reason = check_egress(url)
    if not ok:
        return f"blocked: {reason}"

    try:
        r = httpx.get(
            url,
            headers={"User-Agent": "Quill/0.2"},
            timeout=20,
            follow_redirects=True,
        )
    except Exception as e:
        return f"fetch failed: {e}"

    if r.status_code != 200:
        return f"HTTP {r.status_code}"

    html = r.text
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()[:max_chars]

    flagged, matched = scan_injection(text)
    if flagged:
        return f"[INJECTION WARNING] content withheld ({matched})"

    return f"from {url}:\n{text}"
