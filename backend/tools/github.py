import os
import httpx

from .registry import tool, connector
from vault import vault


API = "https://api.github.com"


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
        {"label": "List my repos", "prompt": "List my GitHub repositories"},
    ],
})
class GitHubConnector:
    pass


def _token() -> str:
    return vault.get_safe("GITHUB_PERSONAL_ACCESS_TOKEN") or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", "")


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _request(method: str, path: str, **kwargs):
    r = httpx.request(method, f"{API}{path}", headers=_headers(), timeout=20, **kwargs)
    if r.status_code == 205:
        return 205, None
    if r.status_code not in (200, 201):
        return r.status_code, r.text[:300]
    return r.status_code, r.json()


@tool
def list_notifications(all: bool = False) -> str:
    """List GitHub notifications. Set all=True to include read ones."""
    status, data = _request("GET", "/notifications",
                            params={"all": "true" if all else "false", "per_page": 30})
    if status != 200:
        return f"GitHub error {status}: {data}"
    if not data:
        return "no notifications"
    return "\n".join(
        f"- [{n['repository']['full_name']}] {n['subject']['type']}: {n['subject']['title']}"
        for n in data[:20]
    )


@tool
def get_notification_details(notification_id: str) -> str:
    """Get full details of a GitHub notification by ID."""
    status, data = _request("GET", f"/notifications/threads/{notification_id}")
    if status != 200:
        return f"GitHub error {status}: {data}"
    return (
        f"repo: {data['repository']['full_name']}\n"
        f"type: {data['subject']['type']}\n"
        f"title: {data['subject']['title']}\n"
        f"reason: {data.get('reason', 'unknown')}"
    )


@tool(destructive=True)
def mark_all_notifications_read() -> str:
    """Mark all GitHub notifications as read."""
    status, _ = _request("PUT", "/notifications")
    return "marked as read" if status == 205 else f"GitHub error {status}"


@tool
def list_repos(limit: int = 20) -> str:
    """List your GitHub repositories, most recently updated first."""
    status, data = _request("GET", "/user/repos",
                            params={"sort": "updated", "per_page": limit})
    if status != 200:
        return f"GitHub error {status}: {data}"
    if not data:
        return "no repositories"
    return "\n".join(
        f"- {r['full_name']} ({'private' if r['private'] else 'public'})"
        for r in data[:limit]
    )


@tool
def list_issues(owner: str, repo: str, state: str = "open") -> str:
    """List issues in a repository. state: open, closed, or all."""
    status, data = _request("GET", f"/repos/{owner}/{repo}/issues",
                            params={"state": state, "per_page": 20})
    if status != 200:
        return f"GitHub error {status}: {data}"
    issues = [i for i in data if "pull_request" not in i]
    if not issues:
        return f"no {state} issues"
    return "\n".join(f"- #{i['number']} [{i['state']}] {i['title']}" for i in issues)


@tool
def list_pull_requests(owner: str, repo: str, state: str = "open") -> str:
    """List pull requests in a repository. state: open, closed, or all."""
    status, data = _request("GET", f"/repos/{owner}/{repo}/pulls",
                            params={"state": state, "per_page": 20})
    if status != 200:
        return f"GitHub error {status}: {data}"
    if not data:
        return f"no {state} pull requests"
    return "\n".join(
        f"- #{p['number']} [{p['state']}] {p['title']} (by {p['user']['login']})"
        for p in data
    )


@tool
def list_commits(owner: str, repo: str, limit: int = 10) -> str:
    """List recent commits on the default branch."""
    status, data = _request("GET", f"/repos/{owner}/{repo}/commits",
                            params={"per_page": limit})
    if status != 200:
        return f"GitHub error {status}: {data}"
    return "\n".join(
        f"- {c['sha'][:7]} {c['commit']['message'].splitlines()[0]}"
        for c in data
    )


@tool(destructive=True)
def create_issue(owner: str, repo: str, title: str, body: str = "") -> str:
    """Create a GitHub issue."""
    status, data = _request("POST", f"/repos/{owner}/{repo}/issues",
                            json={"title": title, "body": body})
    if status not in (200, 201):
        return f"GitHub error {status}: {data}"
    return f"created #{data['number']}: {data['html_url']}"


@tool(destructive=True)
def comment_on_issue(owner: str, repo: str, number: int, body: str) -> str:
    """Post a comment on an issue or PR."""
    status, data = _request("POST", f"/repos/{owner}/{repo}/issues/{number}/comments",
                            json={"body": body})
    if status not in (200, 201):
        return f"GitHub error {status}: {data}"
    return f"comment posted: {data['html_url']}"