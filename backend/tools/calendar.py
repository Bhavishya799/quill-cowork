import httpx
from datetime import datetime, timedelta
from .registry import tool, connector
import oauth

API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

@connector({
    "id": "calendar",
    "name": "Google Calendar",
    "description": "Read and create calendar events",
    "accent": "#4285F4",
    "widgets": [],
    "quick_actions": [
        {"label": "What's on my calendar today?", "prompt": "List my calendar events for today"}
    ],
})
class CalendarConnector:
    pass

def _headers() -> dict:
    tok = oauth.access_token()
    if not tok:
        return {}
    return {"Authorization": f"Bearer {tok}", "Accept": "application/json"}

@tool
def create_calendar_event(title: str, date: str, time: str, duration_minutes: int = 30, description: str = "") -> str:
    """Create a new event in the user's primary Google Calendar. 
    date must be YYYY-MM-DD. time must be 24-hour HH:MM."""
    headers = _headers()
    if not headers:
        return "Calendar not connected. Please authorize Google."

    try:
        start_dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")
        end_dt = start_dt + timedelta(minutes=duration_minutes)
    except ValueError as e:
        return f"Invalid date/time format: {e}"

    payload = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "UTC"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "UTC"},
    }

    try:
        r = httpx.post(API, headers=headers, json=payload, timeout=20)
        if r.status_code not in (200, 201):
            return f"Calendar API error {r.status_code}: {r.text[:200]}"
        data = r.json()
        return f"Event created: {data.get('htmlLink')}"
    except Exception as e:
        return f"Failed to create event: {e}"
