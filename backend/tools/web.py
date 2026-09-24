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

    html = r.text
    html = re.sub(r"<script[^>]*>.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()[:max_chars]

    flagged, matched = scan_injection(text)
    if flagged:
        return f"[INJECTION WARNING] content withheld ({matched})"

    return f"from {current}:\n{text}"