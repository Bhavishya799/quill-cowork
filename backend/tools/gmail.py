import base64
from email.message import EmailMessage

import httpx

from .registry import tool, connector
from safety import scan_injection
import oauth

API = "https://gmail.googleapis.com/gmail/v1/users/me"


@connector({
    "id": "gmail",
    "name": "Gmail",
    "description": "Read, search, draft, and send email",
    "accent": "#EA4335",
    "widgets": [],
    "quick_actions": [
        {"label": "Unread inbox", "prompt": "List my unread Gmail messages from today"},
        {"label": "Summarize recent", "prompt": "Summarize my last 5 Gmail messages"},
    ],
})
class GmailConnector:
    pass


def _headers() -> dict:
    tok = oauth.access_token()
    if not tok:
        return {}
    return {"Authorization": f"Bearer {tok}", "Accept": "application/json"}


def _not_connected() -> str:
    return ("Gmail not connected. Visit http://localhost:8000/oauth/google/start "
            "in your browser to authorize.")


def _request(method: str, path: str, **kwargs):
    headers = _headers()
    if not headers:
        return 401, _not_connected()
    try:
        r = httpx.request(method, f"{API}{path}", headers=headers, timeout=25, **kwargs)
    except Exception as e:
        return 0, f"network error: {e}"
    if r.status_code == 204:
        return 204, None
    if r.status_code not in (200, 201):
        return r.status_code, r.text[:300]
    try:
        return r.status_code, r.json()
    except Exception:
        return r.status_code, r.text[:300]


def _decode_body(payload: dict) -> str:
    def walk(p, prefer_plain=True):
        mime = p.get("mimeType", "")
        body = p.get("body", {}) or {}
        data = body.get("data")
        if data and (mime == "text/plain" or prefer_plain is False):
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                return ""
        parts = p.get("parts") or []
        if parts:
            for part in parts:
                if part.get("mimeType") == "text/plain":
                    t = walk(part)
                    if t:
                        return t
            for part in parts:
                t = walk(part, prefer_plain=False)
                if t:
                    return t
        if data:
            try:
                return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            except Exception:
                return ""
        return ""
    return walk(payload or {})


def _hdr(headers_list, name):
    for h in headers_list or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


@tool
def list_emails(query: str = "", max_results: int = 10) -> str:
    """List Gmail messages. Results are always ordered newest first.

    IMPORTANT: For "recent", "newest", or "latest" emails, leave query EMPTY.
    Do not invent filters like 'is:unread' or 'label:important' unless the
    user specifically asked for unread, starred, or important messages.

    Simple Gmail search terms you may pass only when the user requests them:
      is:unread         - only unread
      is:starred        - only starred
      in:inbox          - only inbox (excludes archived)
      from:alice@x.com  - only from a specific sender
      newer_than:7d     - only the last 7 days
      subject:invoice   - only subject contains word

    Do NOT combine terms with quotes or use multiple labels unless the
    user explicitly described that. When in doubt, pass an empty string."""
    params = {
        "q": query or "",
        "maxResults": max(1, min(max_results, 25)),
    }
    status, data = _request("GET", "/messages", params=params)
    if status != 200:
        return f"Gmail error {status}: {data}"
    msgs = (data or {}).get("messages", [])
    if not msgs:
        return "no messages matched"

    from email.utils import parsedate_to_datetime

    entries = []
    for m in msgs:
        s, det = _request(
            "GET", f"/messages/{m['id']}",
            params={"format": "metadata",
                    "metadataHeaders": ["From", "Subject", "Date"]},
        )
        if s != 200 or not isinstance(det, dict):
            entries.append({
                "date_ts": 0,
                "line": f"- {m['id']} (metadata unavailable)",
            })
            continue
        hs = det.get("payload", {}).get("headers", [])
        date_str = _hdr(hs, "Date")
        try:
            ts = parsedate_to_datetime(date_str).timestamp()
        except Exception:
            ts = 0
        entries.append({
            "date_ts": ts,
            "line": f"- [{m['id']}] {_hdr(hs,'From')} — {_hdr(hs,'Subject')} ({date_str})",
        })

    entries.sort(key=lambda e: e["date_ts"], reverse=True)
    return "\n".join(e["line"] for e in entries)

@tool
def get_email(message_id: str) -> str:
    """Read a Gmail message by ID. Returns headers plus plain-text body."""
    status, data = _request("GET", f"/messages/{message_id}", params={"format": "full"})
    if status != 200:
        return f"Gmail error {status}: {data}"
    if not isinstance(data, dict):
        return "unexpected response"
    hs = data.get("payload", {}).get("headers", [])
    body = _decode_body(data.get("payload", {})).strip()
    if len(body) > 8000:
        body = body[:8000] + "\n…[truncated]"
    flagged, matched = scan_injection(body)
    if flagged:
        body = f"[INJECTION WARNING] content withheld ({matched})"
    return (
        f"From: {_hdr(hs,'From')}\n"
        f"To: {_hdr(hs,'To')}\n"
        f"Subject: {_hdr(hs,'Subject')}\n"
        f"Date: {_hdr(hs,'Date')}\n\n{body}"
    )


@tool
def list_labels() -> str:
    """List Gmail labels (id and name)."""
    status, data = _request("GET", "/labels")
    if status != 200:
        return f"Gmail error {status}: {data}"
    labels = (data or {}).get("labels", [])
    return "\n".join(f"- {l['id']}  {l['name']}" for l in labels)


@tool(destructive=True)
def send_email(to: str, subject: str, body: str, cc: str = "", bcc: str = "") -> str:
    """Send a new email. 'to', 'cc', 'bcc' accept comma-separated addresses."""
    msg = EmailMessage()
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    status, data = _request("POST", "/messages/send", json={"raw": raw})
    if status != 200:
        return f"send failed {status}: {data}"
    return f"sent (id {data.get('id','?')})"


@tool
def create_draft(to: str, subject: str, body: str) -> str:
    """Create a Gmail draft without sending. User can review and send manually."""
    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    status, data = _request("POST", "/drafts", json={"message": {"raw": raw}})
    if status != 200:
        return f"draft failed {status}: {data}"
    return f"draft created (id {data.get('id','?')})"


@tool(destructive=True)
def reply_to_email(message_id: str, body: str) -> str:
    """Reply to an existing Gmail message, preserving the thread."""
    status, orig = _request("GET", f"/messages/{message_id}",
                             params={"format": "metadata",
                                     "metadataHeaders": ["From", "Subject", "Message-ID"]})
    if status != 200 or not isinstance(orig, dict):
        return f"could not load original: {status} {orig}"
    hs = orig.get("payload", {}).get("headers", [])
    to = _hdr(hs, "From")
    subject = _hdr(hs, "Subject")
    if not subject.lower().startswith("re:"):
        subject = "Re: " + subject
    thread_id = orig.get("threadId", "")

    msg = EmailMessage()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    payload = {"raw": raw}
    if thread_id:
        payload["threadId"] = thread_id
    s2, data = _request("POST", "/messages/send", json=payload)
    if s2 != 200:
        return f"reply failed {s2}: {data}"
    return f"replied (id {data.get('id','?')})"


@tool
def mark_as_read(message_id: str) -> str:
    """Remove the UNREAD label from a message."""
    status, _ = _request("POST", f"/messages/{message_id}/modify",
                          json={"removeLabelIds": ["UNREAD"]})
    return "marked as read" if status == 200 else f"failed {status}"


@tool
def archive_email(message_id: str) -> str:
    """Archive a message (remove it from the inbox)."""
    status, _ = _request("POST", f"/messages/{message_id}/modify",
                          json={"removeLabelIds": ["INBOX"]})
    return "archived" if status == 200 else f"failed {status}"


@tool(destructive=True)
def trash_email(message_id: str) -> str:
    """Move a message to Trash (recoverable for 30 days)."""
    status, _ = _request("POST", f"/messages/{message_id}/trash")
    return "trashed" if status == 200 else f"failed {status}"