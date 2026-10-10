"""diag2.py - verbose diagnostic with timeouts and step-by-step prints."""
import asyncio
import sys
import time

sys.path.insert(0, "backend")

print("[1] importing agent...")
t = time.time()
import agent  # noqa: E402
print(f"    ok ({time.time() - t:.2f}s)")

from tools.registry import get_ollama_tools, call_tool  # noqa: E402
from config import settings  # noqa: E402
print(f"[2] MAX_TOOL_ITERATIONS = {settings.MAX_TOOL_ITERATIONS}")

print("[3] checking filter_tools for the prompt...")
tools = get_ollama_tools()
offered = agent.filter_tools("search about the new odyssey movie", tools)
names = [t["function"]["name"] for t in offered]
print(f"    offered: {names}")

print("[4] calling web_search directly (bypasses the model)...")
t = time.time()
try:
    result = call_tool("web_search", {"query": "the new odyssey movie"})
    print(f"    returned in {time.time() - t:.2f}s")
    print(f"    first 200 chars: {result[:200]!r}")
except Exception as e:
    print(f"    FAILED: {type(e).__name__}: {e}")


async def main():
    print("[5] running run_agent with timeout=60s and on_event callback...")
    events = []

    async def cb(ev):
        events.append(ev)
        print(f"    EVENT: {ev.get('type')} | {ev.get('query', '')[:50]}")

    t = time.time()
    try:
        reply, log = await asyncio.wait_for(
            agent.run_agent(
                "search about the new odyssey movie",
                session_id="diag2",
                on_event=cb,
            ),
            timeout=60,
        )
    except asyncio.TimeoutError:
        print(f"    TIMEOUT after 60s")
        print(f"    events fired before timeout: {[e.get('type') for e in events]}")
        return
    except Exception as e:
        import traceback
        print(f"    FAILED: {type(e).__name__}: {e}")
        traceback.print_exc()
        return

    print(f"[6] run_agent returned in {time.time() - t:.2f}s")
    print(f"    reply: {reply[:200]!r}")
    print(f"    tool calls: {[c.get('tool') for c in log]}")
    print(f"    events fired: {[e.get('type') for e in events]}")


asyncio.run(main())
print("[7] done")