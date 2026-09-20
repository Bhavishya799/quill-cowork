"""Quill-Cowork agent loop — provider-agnostic with input safety filtering."""

import json
from typing import List, Dict, Any, Tuple

from config import settings
from providers import get_provider
from safety import is_blocked, REFUSAL_MESSAGE

# Importing tools registers them with the registry
from tools import filesystem  # noqa: F401
from tools import github       # noqa: F401
from tools.registry import get_ollama_tools, call_tool


SYSTEM_PROMPT = (
    "You are Quill, a private local AI assistant. "
    "Use tools to answer. Available: filesystem, github. "
    "Workspace root: D:/Quill-Cowork/workspace. Use absolute paths. "
    "Do only the task asked. Be concise."
)


async def run_agent(
    user_message: str,
    history: List[Dict[str, Any]] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    """Run the tool-calling loop with safety filtering."""

    # ---- LAYER 1: INPUT SAFETY CHECK ----
    # This runs BEFORE the model ever sees the request.
    # Blocks hacking, malware, jailbreaks, and other disallowed categories.
    blocked, reason = is_blocked(user_message)
    if blocked:
        print(f"[Safety] Blocked request ({reason}): {user_message[:80]}")
        return REFUSAL_MESSAGE, []

    # ---- LAYER 2: AGENT LOOP ----
    history = history or []
    tools = get_ollama_tools()
    provider = get_provider()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_message},
    ]

    tool_calls_log: List[Dict[str, Any]] = []

    for _ in range(settings.MAX_TOOL_ITERATIONS):
        msg = provider.chat(messages=messages, tools=tools if tools else None)
        tool_calls = msg.get("tool_calls") or []

        if not tool_calls:
            return (msg.get("content", "") or "").strip(), tool_calls_log

        messages.append(msg)

        for call in tool_calls:
            fn = call["function"]
            name = fn["name"]
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}

            result = call_tool(name, args)
            tool_calls_log.append({
                "tool": name,
                "arguments": args,
                "result": result[:500],
            })
            messages.append({"role": "tool", "name": name, "content": result})

    return "I hit the tool-call limit.", tool_calls_log