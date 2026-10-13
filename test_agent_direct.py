"""test_agent_direct.py - call run_agent directly, no WebSocket."""
import asyncio
import sys
import time

sys.path.insert(0, "backend")
import agent  # noqa: E402


async def main():
    print("calling run_agent('hello')...")
    t = time.time()
    try:
        reply, log = await asyncio.wait_for(
            agent.run_agent("hello", session_id="direct-test"),
            timeout=45,
        )
    except asyncio.TimeoutError:
        print(f"TIMEOUT after {time.time() - t:.1f}s — run_agent is hanging")
        return
    except Exception as e:
        import traceback
        print(f"RAISED after {time.time() - t:.1f}s: {type(e).__name__}: {e}")
        traceback.print_exc()
        return
    print(f"OK in {time.time() - t:.1f}s")
    print(f"reply: {reply[:200]!r}")
    print(f"tool calls: {log}")


asyncio.run(main())