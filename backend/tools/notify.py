"""Send push notifications via self-hosted ntfy."""
import os
import httpx
from .registry import tool, connector
from vault import vault


@connector({
    "id": "notifications",
    "name": "Phone Notifications",
    "description": "Send push notifications to your phone over local WiFi (ntfy)",
    "accent": "#D97757",
    "widgets": [],
    "quick_actions": [
        {"label": "Test notification", "prompt": "Send me a test notification"},
    ],
})
class NotificationsConnector:
    pass


def _base() -> str:
    raw = vault.get_safe("NTFY_URL") or os.getenv("NTFY_URL", "")
    return raw.rstrip("/")


def _topic() -> str:
    return vault.get_safe("NTFY_TOPIC") or os.getenv("NTFY_TOPIC", "quill")


def _token() -> str:
    return vault.get_safe("NTFY_TOKEN") or os.getenv("NTFY_TOKEN", "")


def is_configured() -> bool:
    return bool(_base() and _topic())


@tool
def send_notification(message: str, title: str = "Quill",
                      priority: str = "default") -> str:
    """Send a push notification to the user's phone over local WiFi.
    Use when asked to be notified, pinged, or texted.
    priority: min | low | default | high | urgent."""
    if not is_configured():
        return ("Notifications not configured. Set NTFY_URL and NTFY_TOPIC "
                "in backend/.env.")
    prio = (priority or "default").lower()
    if prio not in ("min", "low", "default", "high", "urgent"):
        prio = "default"
    headers = {
        "Title": (title or "Quill")[:64],
        "Priority": prio,
        "Tags": "robot",
    }
    tok = _token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    try:
        r = httpx.post(
            f"{_base()}/{_topic()}",
            content=(message or "").encode("utf-8"),
            headers=headers,
            timeout=10,
        )
    except Exception as e:
        return f"notification failed: {type(e).__name__}: {e}"
    if r.status_code != 200:
        return f"notification failed: HTTP {r.status_code} {r.text[:200]}"
    return f"notification sent to topic '{_topic()}'"
