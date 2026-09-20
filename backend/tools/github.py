"""GitHub tools — notifications via REST API."""

import os
import httpx

from .registry import tool, connector


GITHUB_API = "https://api.github.com"


@connector({
    "id": "github",
    "name": "GitHub",
    "description": "Notifications, PRs, and issues",
    "accent": "#7C5CFF",
    "widgets": [
        {"type": "counter", "id": "unread", "label": "Unread", "tool": "list_notifications"},
    ],
    "quick_actions": [
        {"label": "Check notifications", "prompt": "Check my GitHub notifications"},
        {"label": "Mark all read", "prompt": "Mark all my GitHub notifications as read"},
    ],
})
class GitHubConnector:
    """Declares the GitHub connector manifest."""
    pass


from vault import vault


def _get_token() -> str:
    """Read the token from the encrypted vault, falling back to .env."""
    return vault.get("GITHUB_PERSONAL_ACCESS_TOKEN") or os.getenv(
        "GITHUB_PERSONAL_ACCESS_TOKEN", ""
    )


def _headers() -> dict:
    token = _get_token()
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


@tool
def list_notifications(all: bool = False) -> str:
    """List GitHub notifications. Set all=True to include already-read ones."""
    params = {"all": "true" if all else "false", "per_page": 30}
    r = httpx.get(f"{GITHUB_API}/notifications", headers=_headers(), params=params, timeout=20)
    if r.status_code != 200:
        return f"GitHub API error {r.status_code}: {r.text[:300]}"
    data = r.json()
    if not data:
        return "No notifications."
    lines = []
    for n in data[:20]:
        repo = n["repository"]["full_name"]
        subject = n["subject"]
        lines.append(f"- [{repo}] {subject['type']}: {subject['title']}")
    return "\n".join(lines)


@tool
def get_notification_details(notification_id: str) -> str:
    """Get full details of a single GitHub notification by its ID."""
    r = httpx.get(
        f"{GITHUB_API}/notifications/threads/{notification_id}",
        headers=_headers(),
        timeout=20,
    )
    if r.status_code != 200:
        return f"GitHub API error {r.status_code}: {r.text[:300]}"
    data = r.json()
    return (
        f"Repository: {data['repository']['full_name']}\n"
        f"Type: {data['subject']['type']}\n"
        f"Title: {data['subject']['title']}\n"
        f"Reason: {data.get('reason', 'unknown')}\n"
        f"Updated: {data.get('updated_at', 'unknown')}"
    )


@tool
def mark_all_notifications_read() -> str:
    """Mark all GitHub notifications as read."""
    r = httpx.put(f"{GITHUB_API}/notifications", headers=_headers(), timeout=20)
    if r.status_code == 205:
        return "All notifications marked as read."
    return f"GitHub API error {r.status_code}: {r.text[:300]}"