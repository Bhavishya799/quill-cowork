import asyncio
import json
import uuid
from typing import List, Dict, Any, Tuple, Callable, Awaitable, Optional

from config import settings
from providers import get_provider
from safety import (
    is_blocked, REFUSAL_MESSAGE,
    scan_output, redact_output,
    scan_injection,
)
from rate_limit import check_rate
from audit import log_event

from tools import load_all_tools
load_all_tools()

from tools.registry import get_ollama_tools, call_tool, is_destructive


SYSTEM_PROMPT = (
    "You are Quill. When the user asks you to do something, "
    "you MUST call a tool. Do not say you did something unless you called the tool. "
    "Workspace root: D:/Quill-Cowork/workspace. "
    "Be concise."
)

ConfirmCallback = Callable[[str, str, Dict[str, Any]], Awaitable[bool]]


def filter_tools(message: str, all_tools: list) -> list:
    m = message.lower()
    keep = set()

    if any(w in m for w in ["file", "folder", "read", "list", "show", "workspace", "search"]):
        keep.update(["list_directory", "read_file", "search_files"])
    if any(w in m for w in ["write", "create", "save", "make a file"]):
        keep.add("write_file")
    if "notification" in m:
        keep.update(["list_notifications", "get_notification_details", "mark_all_notifications_read"])
    if any(w in m for w in ["repo", "repository", "repositories"]):
        keep.add("list_repos")
    if "issue" in m:
        keep.update(["list_issues", "create_issue", "comment_on_issue"])
    if any(w in m for w in ["pr", "pull request", "pull requests"]):
        keep.add("list_pull_requests")
    if "commit" in m:
        keep.add("list_commits")
    if any(w in m for w in ["http", "url", "fetch", "website", "page", "web"]):
        keep.add("fetch_page")

    if not keep:
        keep = {"list_directory", "list_notifications"}

    return [t for t in all_tools if t["function"]["name"] in keep]


async def run_agent(
    user_message: str,
    history: List[Dict[str, Any]] = None,
    model: str = None,
    confirm_callback: Optional[ConfirmCallback] = None,
) -> Tuple[str, List[Dict[str, Any]]]:
    blocked, reason = is_blocked(user_message)
    if blocked:
        log_event("input_blocked", reason=reason, preview=user_message[:100])
        return REFUSAL_MESSAGE, []

    history = history or []
    all_tools = get_ollama_tools()
    tools = filter_tools(user_message, all_tools)
    provider = get_provider()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *history,
        {"role": "user", "content": user_message},
    ]

    log: List[Dict[str, Any]] = []

    for _ in range(settings.MAX_TOOL_ITERATIONS):
        msg = await asyncio.to_thread(
            provider.chat,
            messages=messages,
            tools=tools or None,
            model=model,
        )
        calls = msg.get("tool_calls") or []

        if not calls:
            reply = (msg.get("content") or "").strip()
            has_leak, kinds = scan_output(reply)
            if has_leak:
                log_event("output_redacted", kinds=kinds)
                reply = redact_output(reply) + "\n\n[Content redacted.]"
            return reply, log

        messages.append(msg)

        for call in calls:
            fn = call["function"]
            name = fn["name"]
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}

            allowed, rreason = check_rate(name)
            if not allowed:
                result = f"Rate limited: {rreason}"
                log_event("rate_limited", tool=name)
            elif is_destructive(name):
                if confirm_callback is None:
                    result = "This action requires interactive confirmation."
                    log_event("confirm_unavailable", tool=name)
                else:
                    call_id = uuid.uuid4().hex[:12]
                    approved = await confirm_callback(call_id, name, args)
                    if approved:
                        result = await asyncio.to_thread(call_tool, name, args)
                        log_event("confirm_approved", tool=name, args=args)
                    else:
                        result = "User declined this action."
                        log_event("confirm_declined", tool=name, args=args)
            else:
                result = await asyncio.to_thread(call_tool, name, args)
                flagged, matched = scan_injection(result)
                if flagged:
                    log_event("injection_detected", tool=name, matched=matched)
                    result = f"[INJECTION WARNING] content withheld ({matched})"

            log_event("tool_call", tool=name, args=args, result=result[:200])
            log.append({"tool": name, "arguments": args, "result": result[:500]})
            messages.append({"role": "tool", "name": name, "content": result})

    return "Tool-call limit reached.", log