import asyncio
import json
import re
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
    "You are Quill. When the user's message asks for an action "
    "(reading files, checking notifications, searching, fetching, "
    "sending email, looking something up, working on a codebase), call a tool. "
    "For casual conversation or simple questions, reply directly without a tool. "
    "If the user asks about a topic, product, person, or current event you "
    "don't have knowledge of, use web_search or search_wikipedia before "
    "answering — do not guess and do not list files. "
    "Never claim to have done something unless you called the tool. "
    "When the user asks for recent, latest, or newest emails, call "
    "list_emails with an empty query. Do not invent Gmail filters. "
    "Only add filters when the user asks for unread, starred, or from: someone. "
    "For codebase work: list_codebases shows what is connected, "
    "codebase_tree sees the layout, codebase_symbols or codebase_find_symbol "
    "locate code, codebase_read reads individual files, "
    "codebase_patch makes small edits. "
    "Only call codebase_read_all when the codebase is small and you truly "
    "need everything — it is expensive. "
    "Workspace root: D:/Quill-Cowork/workspace. "
    "When listing or reading workspace files, pass '.' or a relative path "
    "(e.g. 'notes.txt', 'subfolder/file.txt') — do NOT pass '/workspace' or "
    "absolute paths unless the user gave one. "
    "If the user's message contains '[attached files: name at /path]', the file "
    "is already on disk at that path. Use that path directly — do not ask the "
    "user for a location again. For .zip/.tar/.tar.gz, call connect_codebase "
    "with the path to extract and index it. "
    "Be concise. Never use emoji or emoticons. No exclamation marks. "
    "No cheerful filler or openers like 'Sure!' or 'Great!'. Plain prose only."
)

ConfirmCallback = Callable[[str, str, Dict[str, Any]], Awaitable[bool]]


# =====================================================================
# Session working set — a rolling note about what the model has read
# =====================================================================

_WORKING_SET: Dict[str, list] = {}
_WORKING_SET_MAX = 30


def _ws_add(session_id: str, line: str):
    key = session_id or "default"
    lines = _WORKING_SET.setdefault(key, [])
    if line in lines:
        return
    lines.append(line)
    if len(lines) > _WORKING_SET_MAX:
        _WORKING_SET[key] = lines[-_WORKING_SET_MAX:]


def _ws_render(session_id: str) -> str:
    lines = _WORKING_SET.get(session_id or "default", [])
    if not lines:
        return ""
    return ("Notes from this session (what you have already done — do not redo "
            "these steps):\n" + "\n".join(f"- {l}" for l in lines))


def _ws_clear(session_id: str):
    _WORKING_SET.pop(session_id or "default", None)


def _note_tool_call(session_id: str, name: str, args: dict, result: str):
    if session_id is None:
        return
    if name == "codebase_read":
        path = args.get("path", "?")
        _ws_add(session_id, f"read {path}")
    elif name == "codebase_read_all":
        _ws_add(session_id, f"read the entire codebase '{args.get('name','?')}'")
    elif name == "codebase_write":
        path = args.get("path", "?")
        _ws_add(session_id, f"wrote {path}")
    elif name == "codebase_patch":
        path = args.get("path", "?")
        _ws_add(session_id, f"patched {path}")
    elif name == "codebase_search":
        _ws_add(session_id, f"searched '{args.get('query','?')}'")
    elif name == "codebase_grep":
        _ws_add(session_id, f"grepped /{args.get('pattern','?')}/")
    elif name == "codebase_git":
        action = args.get("action", "?")
        _ws_add(session_id, f"git {action} on '{args.get('name','?')}'")


# =====================================================================
# Tool filter
# =====================================================================

def filter_tools(message: str, all_tools: list) -> list:
    m = message.lower()
    keep = set()

    def has(*words):
        return any(re.search(rf"\b{re.escape(w)}", m) for w in words)

    # Filesystem
    if has("file", "folder", "directory", "workspace", "find"):
        keep.update(["list_directory", "read_file", "search_files"])
    if has("read", "open") and has("file", "notes", "txt", "md"):
        keep.update(["read_file", "list_directory"])
    if has("list") and has("file", "folder", "directory", "workspace"):
        keep.add("list_directory")
    if has("write", "create", "save", "make", "add"):
        keep.add("write_file")
    if has("search") and has("file", "folder", "workspace"):
        keep.add("search_files")

    # GitHub
    if has("notification", "notifications", "notify"):
        keep.update(["list_notifications", "get_notification_details",
                     "mark_all_notifications_read"])
    if has("repo", "repository", "repositories"):
        keep.add("list_repos")
    if has("issue", "issues"):
        keep.update(["list_issues", "create_issue", "comment_on_issue"])
    if has("pr", "prs", "pull") and has("request", "requests", "merge"):
        keep.add("list_pull_requests")
    if has("commit", "commits"):
        keep.add("list_commits")

    # Web / lookup
    if has("http", "url", "website", "webpage", "link"):
        keep.update(["fetch_page", "web_search"])
    if has("fetch", "download", "scrape"):
        keep.add("fetch_page")
    if has("search", "google", "look", "find", "research", "latest", "news",
           "summarise", "summarize", "summary", "tell", "explain",
           "what", "who", "when", "where", "why", "how"):
        keep.update(["web_search", "search_wikipedia", "get_wikipedia_article"])
    if has("wiki", "wikipedia"):
        keep.update(["search_wikipedia", "get_wikipedia_article"])

    # Email
    if has("email", "emails", "mail", "gmail", "inbox"):
        keep.update(["list_emails", "get_email", "send_email",
                     "create_draft", "reply_to_email", "list_labels",
                     "mark_as_read", "archive_email", "trash_email"])

    # Codebase
    if has("codebase", "codebases", "connect", "index"):
        keep.update(["connect_codebase", "list_codebases", "disconnect_codebase",
                     "codebase_info", "codebase_tree", "codebase_search",
                     "codebase_grep", "codebase_read", "codebase_read_all",
                     "codebase_write", "codebase_git",
                     "codebase_symbols", "codebase_find_symbol",
                     "codebase_imports", "codebase_patch"])
    if has("symbol", "symbols", "function", "class", "method"):
        keep.update(["codebase_symbols", "codebase_find_symbol",
                     "codebase_read", "codebase_tree"])
    if has("import", "imports", "dependency", "dependencies"):
        keep.update(["codebase_imports", "codebase_tree"])
    if has("patch", "edit", "modify", "change", "fix", "rewrite"):
        keep.update(["codebase_patch", "codebase_read", "codebase_search",
                     "codebase_write"])
    if has("search") and has("code", "codebase", "project"):
        keep.update(["codebase_search", "codebase_grep"])
    if has("read") and has("code", "codebase", "project"):
        keep.update(["codebase_read", "codebase_search", "codebase_symbols"])
    if has("commit", "push") and has("git", "codebase", "repo", "project"):
        keep.update(["codebase_git", "codebase_info"])
    if has("review", "audit", "analyze", "analyse", "inspect", "suggest", "improve"):
        keep.update(["codebase_symbols", "codebase_tree", "codebase_info",
                     "codebase_search", "codebase_grep", "codebase_read",
                     "codebase_read_all"])

    # Grants
    if has("grant", "grants", "granted", "access", "permission"):
        keep.update(["list_grants", "request_folder_grant"])

    if not keep:
        return all_tools
    return [t for t in all_tools if t["function"]["name"] in keep]


# =====================================================================
# Agent loop
# =====================================================================

async def run_agent(
    user_message: str,
    history: List[Dict[str, Any]] = None,
    model: str = None,
    confirm_callback: Optional[ConfirmCallback] = None,
    session_id: str = "default",
) -> Tuple[str, List[Dict[str, Any]]]:
    blocked, reason = is_blocked(user_message)
    if blocked:
        log_event("input_blocked", reason=reason, preview=user_message[:100])
        return REFUSAL_MESSAGE, []

    history = history or []
    all_tools = get_ollama_tools()
    tools = filter_tools(user_message, all_tools)
    provider = get_provider()

    system_content = SYSTEM_PROMPT
    ws = _ws_render(session_id)
    if ws:
        system_content = SYSTEM_PROMPT + "\n\n" + ws

    messages = [
        {"role": "system", "content": system_content},
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
            _note_tool_call(session_id, name, args, result)
            messages.append({"role": "tool", "tool_name": name, "content": result})

    return "Tool-call limit reached.", log


def clear_working_set(session_id: str):
    _ws_clear(session_id)