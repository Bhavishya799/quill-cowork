"""trace_ws.py - add a print inside _on_event to see if it's invoked."""
from pathlib import Path

p = Path("backend/main.py")
src = p.read_text(encoding="utf-8")

if "[trace] _on_event called" in src:
    print("[SKIP] already traced")
    raise SystemExit(0)

# Insert print inside the _on_event body
old = """        async def _on_event(ev):
            try:
                await ws.send_json(ev)
            except Exception:
                pass"""

new = """        async def _on_event(ev):
            print(f"[trace] _on_event called: {ev.get('type')}", flush=True)
            try:
                await ws.send_json(ev)
                print(f"[trace] _on_event sent: {ev.get('type')}", flush=True)
            except Exception as e:
                print(f"[trace] _on_event send FAILED: {e}", flush=True)"""

if old in src:
    src = src.replace(old, new, 1)
    p.write_text(src, encoding="utf-8")
    print("[OK] trace added")
elif "async def _on_event(ev):" in src:
    print("[WARN] _on_event exists but body differs")
    print("       open backend/main.py, find 'async def _on_event'")
    print("       and paste the 4 lines after it")
else:
    print("[FAIL] _on_event not found in main.py")