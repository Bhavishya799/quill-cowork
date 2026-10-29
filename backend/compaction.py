"""Context compaction for Quill-Cowork.

Reduces the in-flight message list when it approaches the model's context
window. The system prompt is preserved verbatim. Old user/assistant/tool
turns are summarized by the model into a structured "prior context" block;
every message from the most recent user turn onward stays verbatim so the
current tool sequence is never cut mid-flight.

Session-only: chat.db is untouched. Reload from the sidebar restores the
uncompacted transcript. Manual /compact mutates the in-memory session.

Env:
  CONTEXT_WINDOW         model context size (default 8192, matches num_ctx)
  CONTEXT_COMPACT_AT     fraction that triggers auto-compaction (default 0.85)
  CONTEXT_KEEP_RECENT    messages kept verbatim before the current turn (default 8)
  CONTEXT_AUTO           enable auto-compaction (default 1)
"""
from __future__ import annotations

import json
import os
from typing import Dict, List, Optional, Tuple


SUMMARY_SCHEMA = {
    "type": "object",
    "required": ["current_task", "key_facts", "pending"],
    "properties": {
        "current_task": {"type": "string"},
        "key_facts": {"type": "array", "items": {"type": "string"}},
        "files_touched": {"type": "array", "items": {"type": "string"}},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "errors": {"type": "array", "items": {"type": "string"}},
        "pending": {"type": "array", "items": {"type": "string"}},
        "tools_used": {"type": "array", "items": {"type": "string"}},
    },
}

_SUMMARY_SYSTEM = (
    "You are a context summarizer for Quill, an autonomous AI assistant. "
    "You will be given a transcript of a conversation between the user and "
    "the assistant, including tool calls and tool results. Produce a JSON "
    "object that captures everything the assistant needs to continue the "
    "task without the transcript. Be terse and concrete. Do not invent "
    "facts. Ignore greetings and small talk. Focus on: what the user wants, "
    "what has already been done, which files were touched, decisions made, "
    "errors encountered, and what remains."
)


def _window() -> int:
    try:
        return max(1024, int(os.getenv("CONTEXT_WINDOW", "8192")))
    except ValueError:
        return 8192


def _threshold() -> float:
    try:
        return min(0.99, max(0.5, float(os.getenv("CONTEXT_COMPACT_AT", "0.85"))))
    except ValueError:
        return 0.85


def _keep_recent() -> int:
    try:
        return max(2, int(os.getenv("CONTEXT_KEEP_RECENT", "8")))
    except ValueError:
        return 8


def _auto_enabled() -> bool:
    return os.getenv("CONTEXT_AUTO", "1") not in ("0", "false", "False")


def estimate_tokens(messages: List[Dict]) -> int:
    """Rough token count. English text averages ~4 chars/token."""
    total = 0
    for m in messages or []:
        content = m.get("content") or ""
        total += len(content) // 4
        total += 4
        calls = m.get("tool_calls")
        if calls:
            try:
                total += len(json.dumps(calls)) // 4
            except Exception:
                total += 64
    return total


def should_compact(messages: List[Dict]) -> bool:
    if not _auto_enabled():
        return False
    return estimate_tokens(messages) >= int(_window() * _threshold())


def usage(messages: List[Dict]) -> Dict:
    used = estimate_tokens(messages)
    window = _window()
    frac = (used / window) if window else 0.0
    return {
        "used": used,
        "window": window,
        "fraction": round(frac, 3),
        "threshold": _threshold(),
        "over_threshold": used >= int(window * _threshold()),
    }


def _safe_cut(convo: List[Dict], keep_recent: int) -> int:
    """Where to cut the conversation. Everything from the last user
    message onwards is preserved (current turn). Additionally preserve
    up to keep_recent messages before it. Never cut a tool result away
    from its assistant parent."""
    if not convo:
        return 0
    last_user_idx = -1
    for i in range(len(convo) - 1, -1, -1):
        if convo[i].get("role") == "user":
            last_user_idx = i
            break
    if last_user_idx < 0:
        return 0
    cut = min(max(0, len(convo) - keep_recent), last_user_idx)
    while cut > 0 and convo[cut].get("role") == "tool":
        cut -= 1
    return cut


def _build_request(old_messages: List[Dict]) -> str:
    lines = ["Transcript to summarize:\n"]
    for m in old_messages:
        role = m.get("role", "?")
        content = (m.get("content") or "").strip()
        if not content and not m.get("tool_calls"):
            continue
        if len(content) > 4000:
            content = content[:4000] + " …[truncated]"
        calls = m.get("tool_calls") or []
        if calls:
            call_lines = []
            for c in calls:
                fn = c.get("function") or {}
                name = fn.get("name", "?")
                args = fn.get("arguments") or {}
                try:
                    arg_str = json.dumps(args, default=str)[:200]
                except Exception:
                    arg_str = str(args)[:200]
                call_lines.append(f"  -> {name}({arg_str})")
            content = (content + "\n" if content else "") + "TOOL CALLS:\n" + "\n".join(call_lines)
        lines.append(f"[{role}] {content}")
    lines.append("\nReturn JSON matching the schema. Do not include markdown.")
    return "\n".join(lines)


def _render(summary: Dict) -> str:
    parts = ["[Prior context — compacted]"]
    task = (summary.get("current_task") or "").strip()
    if task:
        parts.append(f"Current task: {task}")
    for key, label in [
        ("key_facts", "Key facts"),
        ("decisions", "Decisions"),
        ("files_touched", "Files touched"),
        ("errors", "Errors"),
        ("tools_used", "Tools used"),
        ("pending", "Pending"),
    ]:
        items = summary.get(key) or []
        if items:
            parts.append(f"{label}:")
            for it in items[:20]:
                parts.append(f"  - {it}")
    return "\n".join(parts)


def _parse_json(raw: str) -> Dict:
    raw = (raw or "").strip()
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        pass
    if "```" in raw:
        parts = raw.split("```")
        for p in parts:
            p = p.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            try:
                return json.loads(p)
            except Exception:
                continue
    return {}


def compact_convo(
    convo: List[Dict],
    provider,
    model: Optional[str] = None,
    keep_recent: Optional[int] = None,
) -> Tuple[List[Dict], Optional[Dict], bool]:
    """Compact a system-less conversation. Returns (new_convo, summary, did)."""
    keep_recent = keep_recent if keep_recent is not None else _keep_recent()
    if len(convo) < keep_recent + 3:
        return convo, None, False

    cut = _safe_cut(convo, keep_recent)
    if cut <= 0:
        return convo, None, False

    old = convo[:cut]
    recent = convo[cut:]

    try:
        resp = provider.chat(
            messages=[
                {"role": "system", "content": _SUMMARY_SYSTEM},
                {"role": "user", "content": _build_request(old)},
            ],
            tools=None,
            model=model,
            format=SUMMARY_SCHEMA,
        )
        summary = _parse_json(resp.get("content") or "")
        if not isinstance(summary, dict):
            summary = {}
    except Exception:
        summary = {}

    if not summary:
        summary = {
            "current_task": "(summary unavailable)",
            "key_facts": [f"{len(old)} earlier turns omitted"],
            "pending": [],
        }

    block = _render(summary)
    compacted = [
        {"role": "user", "content": block},
        {"role": "assistant", "content": "Understood. Continuing from the summary."},
    ] + recent
    return compacted, summary, True


def compact(
    messages: List[Dict],
    provider,
    model: Optional[str] = None,
    keep_recent: Optional[int] = None,
) -> Tuple[List[Dict], Optional[Dict], bool]:
    """Compact a full message list, preserving the system prompt."""
    system_msgs = [m for m in messages if m.get("role") == "system"]
    convo = [m for m in messages if m.get("role") != "system"]
    compacted_convo, summary, did = compact_convo(convo, provider, model, keep_recent)
    if not did:
        return messages, None, False
    return system_msgs + compacted_convo, summary, True
