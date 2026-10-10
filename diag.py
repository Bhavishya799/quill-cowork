"""diag.py - run the agent directly with an on_event callback to see
whether the search events fire. Answers the one question left:
does run_agent actually invoke on_event for a web_search call?
"""
import asyncio
import sys

sys.path.insert(0, "backend")
import agent  # noqa: E402


async def main():
    events = []

    async def cb(ev):
        events.append(ev)
        print(f"EVENT: {ev.get('type')} | {ev.get('query', '')[:60]}")

    prompt = "search about the new odyssey movie"
    print(f"prompt: {prompt}")
    print("-" * 60)

    reply, log = await agent.run_agent(
        prompt, session_id="diag", on_event=cb
    )

    print("-" * 60)
    print(f"reply: {reply[:200]}")
    print(f"tool calls made: {[c.get('tool') for c in log]}")
    print(f"events fired: {[e.get('type') for e in events]}")
    print()

    if not events:
        print("VERDICT: on_event never fired.")
        print("         The intercept branch was not reached, or")
        print("         'on_event is not None' evaluated to False.")
    elif "search_start" not in [e.get("type") for e in events]:
        print("VERDICT: events fired but no search_start.")
        print("         Something else triggered the callback.")
    else:
        print("VERDICT: agent fired search_start correctly.")
        print("         The bug is in main.py's WebSocket delivery.")


if __name__ == "__main__":
    asyncio.run(main())