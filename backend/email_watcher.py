import asyncio
import json
import re
import time
import httpx
import ollama
from config import settings
import tools.gmail as gmail
import tools.calendar as calendar

PROCESSED_EMAILS = set()

async def check_inbox():
    print("[watcher] Starting Email Assistant Daemon...")
    while True:
        try:
            # 1. Fetch unread emails from the last hour
            status, data = gmail._request("GET", "/messages", params={"q": "is:unread newer_than:1h", "maxResults": 3})
            if status != 200 or not data:
                await asyncio.sleep(60)
                continue
                
            msgs = data.get("messages", [])
            for m in msgs:
                msg_id = m["id"]
                if msg_id in PROCESSED_EMAILS:
                    continue

                # 2. Read the email
                status, email_data = gmail._request("GET", f"/messages/{msg_id}", params={"format": "full"})
                if status != 200:
                    continue
                    
                body = gmail._decode_body(email_data.get("payload", {}))
                subject = gmail._hdr(email_data.get("payload", {}).get("headers", []), "Subject")
                
                # 3. Mark as read immediately so we don't loop
                gmail.mark_as_read(msg_id)
                PROCESSED_EMAILS.add(msg_id)

                # 4. Use the small model to extract event details
                print(f"[watcher] Analyzing email: {subject}")
                client = ollama.Client(host=settings.OLLAMA_HOST)
                prompt = f'''Analyze this email. Does it contain a meeting, event, or appointment?
If YES, extract the details and return ONLY valid JSON:
{{"title": "Event Title", "date": "YYYY-MM-DD", "time": "HH:MM", "duration": 30}}
If NO, return exactly: {{}}

Email Body:
{body[:2000]}'''

                try:
                    resp = client.chat(model="quill-cpu-fast", messages=[{"role": "user", "content": prompt}], format="json")
                    result_text = resp["message"]["content"]
                    event_data = json.loads(result_text)
                except Exception as e:
                    print(f"[watcher] AI extraction failed: {e}")
                    continue

                if event_data and "title" in event_data:
                    print(f"[watcher] Event detected: {event_data['title']} on {event_data['date']}")
                    # 5. Create the calendar event
                    cal_result = calendar.create_calendar_event(
                        title=event_data.get("title", "Untitled Event"),
                        date=event_data.get("date", ""),
                        time=event_data.get("time", "12:00"),
                        duration_minutes=int(event_data.get("duration", 30)),
                        description=f"Automatically added from email: {subject}"
                    )
                    
                    # 6. Reply to the user confirming
                    reply_body = f"I automatically added '{event_data['title']}' to your calendar for {event_data['date']} at {event_data['time']}.\n\nStatus: {cal_result}"
                    gmail.send_email(to="me", subject=f"Re: {subject}", body=reply_body)

        except Exception as e:
            print(f"[watcher] Error in loop: {e}")
            
        await asyncio.sleep(60)  # Check every minute
