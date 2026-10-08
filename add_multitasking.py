"""Add multitasking to Quill-Cowork agent.

- Parallel non-destructive tool calls in backend/agent.py
- MAX_PARALLEL_TOOLS config
- Concurrent Gmail metadata fetch
- Cleanup safety.py duplicate _EXTRA_BLOCKED
- Add MAX_PARALLEL_TOOLS to .env.example and .env if missing
"""
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
BACKEND = ROOT / "backend"
AGENT = BACKEND / "agent.py"
CONFIG = BACKEND / "config.py"
GMAIL = BACKEND / "tools" / "gmail.py"
SAFETY = BACKEND / "safety.py"
ENV_EXAMPLE = BACKEND / ".env.example"
ENV = BACKEND / ".env"


def patch(path, old, new, label):
    if not path.exists():
        print(f"SKIP {path}: not found")
        return
    src = path.read_text(encoding="utf-8")
    if new in src:
        print(f"SKIP {path.name}: already patched ({label})")
        return
    if old not in src:
        print(f"WARN {path.name}: anchor missing ({label})")
        return
    path.write_text(src.replace(old, new, 1), encoding="utf-8")
    print(f"OK {path.name}: {label}")


# 1. config.py
patch(
    CONFIG,
    "    MAX_TOOL_ITERATIONS = int(os.getenv(\"MAX_TOOL_ITERATIONS\", \"20\"))\n",
    "    MAX_TOOL_ITERATIONS = int(os.getenv(\"MAX_TOOL_ITERATIONS\", \"20\"))\n"
    "    MAX_PARALLEL_TOOLS = int(os.getenv(\"MAX_PARALLEL_TOOLS\", \"4\"))\n",
    "MAX_PARALLEL_TOOLS",
)

# 2. .env.example
if ENV_EXAMPLE.exists():
    txt = ENV_EXAMPLE.read_text(encoding="utf-8")
    if "MAX_PARALLEL_TOOLS" not in txt:
        txt = txt.replace(
            "MAX_TOOL_ITERATIONS=20\n",
            "MAX_TOOL_ITERATIONS=20\nMAX_PARALLEL_TOOLS=4\n",
            1,
        )
        ENV_EXAMPLE.write_text(txt, encoding="utf-8")
        print("OK .env.example: MAX_PARALLEL_TOOLS")

# 3. .env: append only, do not touch secrets
if ENV.exists():
    txt = ENV.read_text(encoding="utf-8")
    if "MAX_PARALLEL_TOOLS" not in txt:
        txt = txt.rstrip() + "\nMAX_PARALLEL_TOOLS=4\n"
        ENV.write_text(txt, encoding="utf-8")
        print("OK .env: MAX_PARALLEL_TOOLS appended")
    if "Get-Process" in txt or "Stop-Process" in txt:
        print("WARNING: backend/.env contains a PowerShell splice.")
        print("         Fix manually: remove 'Get-Process python ...' and set")
        print("         DISABLED_CONNECTORS= on its own line.")

# 4. safety.py duplicate cleanup
if SAFETY.exists():
    src = SAFETY.read_text(encoding="utf-8")
    block = '''_EXTRA_BLOCKED = re.compile(
    r"\\b(?:"
    r"hack(?:er|ers|ing|ed|s)?|"
    r"phish(?:er|ers|ing|ed|es)?|"
    r"exfiltrat(?:e|es|ed|ing|ion|ions)?|"
    r"bypass(?:es|ed|ing)?\\s+(?:antivirus|av|firewall|security|auth\\w*)"
    r")\\b",
    re.IGNORECASE,
)
'''
    if src.count(block) > 1:
        src = src.replace(block + "\n\n" + block, block, 1)
        print("OK safety.py: removed duplicate _EXTRA_BLOCKED")

    dup_check = '''    if _EXTRA_BLOCKED.search(text):
        return True, "blocked_content"
    if _EXTRA_BLOCKED.search(text):
        return True, "blocked_content"
'''
    if dup_check in src:
        src = src.replace(
            dup_check,
            '''    if _EXTRA_BLOCKED.search(text):
        return True, "blocked_content"
''',
            1,
        )
        print("OK safety.py: removed duplicate check")
    SAFETY.write_text(src, encoding="utf-8")

# 5. Gmail list_emails: concurrent metadata fetch
if GMAIL.exists():
    src = GMAIL.read_text(encoding="utf-8")
    if "from concurrent.futures import ThreadPoolExecutor" not in src:
        src = src.replace(
            "import base64\n",
            "import base64\nfrom concurrent.futures import ThreadPoolExecutor\n",
            1,
        )

    old_loop = '''    entries = []
    for m in msgs:
        s, det = _request(
            "GET", f"/messages/{m['id']}",
            params={"format": "metadata",
                    "metadataHeaders": ["From", "Subject", "Date"]},
        )
        if s != 200 or not isinstance(det, dict):
            entries.append({
                "date_ts": 0,
                "line": f"- {m['id']} (metadata unavailable)",
            })
            continue
        hs = det.get("payload", {}).get("headers", [])
        date_str = _hdr(hs, "Date")
        try:
            ts = parsedate_to_datetime(date_str).timestamp()
        except Exception:
            ts = 0
        entries.append({
            "date_ts": ts,
            "line": f"- [{m['id']}] {_hdr(hs,'From')} — {_hdr(hs,'Subject')} ({date_str})",
        })

    entries.sort(key=lambda e: e["date_ts"], reverse=True)
'''
    new_loop = '''    def _fetch_meta(m):
        s, det = _request(
            "GET", f"/messages/{m['id']}",
            params={"format": "metadata",
                    "metadataHeaders": ["From", "Subject", "Date"]},
        )
        if s != 200 or not isinstance(det, dict):
            return {
                "date_ts": 0,
                "line": f"- {m['id']} (metadata unavailable)",
            }
        hs = det.get("payload", {}).get("headers", [])
        date_str = _hdr(hs, "Date")
        try:
            ts = parsedate_to_datetime(date_str).timestamp()
        except Exception:
            ts = 0
        return {
            "date_ts": ts,
            "line": f"- [{m['id']}] {_hdr(hs,'From')} — {_hdr(hs,'Subject')} ({date_str})",
        }

    with ThreadPoolExecutor(max_workers=8) as ex:
        entries = list(ex.map(_fetch_meta, msgs))

    entries.sort(key=lambda e: e["date_ts"], reverse=True)
'''
    if old_loop in src:
        src = src.replace(old_loop, new_loop, 1)
        print("OK gmail.py: concurrent metadata fetch")
    GMAIL.write_text(src, encoding="utf-8")

# 6. agent.py: parallel non-destructive tool calls
if AGENT.exists():
    src = AGENT.read_text(encoding="utf-8")
    start_marker = "        for call in calls:\n"
    end_marker = "\n    return \"Tool-call limit reached.\", log"
    start = src.find(start_marker)
    end = src.find(end_marker, start)

    if start == -1 or end == -1:
        print("WARN agent.py: could not locate tool-call block; patch manually")
    else:
        new_block = '''        async def _execute_tool_call(name: str, args: dict):
            allowed, rreason = check_rate(name)
            if not allowed:
                log_event("rate_limited", tool=name)
                return f"Rate limited: {rreason}"

            if is_destructive(name):
                if confirm_callback is None:
                    log_event("confirm_unavailable", tool=name)
                    return "This action requires interactive confirmation."
                call_id = uuid.uuid4().hex[:12]
                approved = await confirm_callback(call_id, name, args)
                if approved:
                    result = await asyncio.to_thread(call_tool, name, args)
                    log_event("confirm_approved", tool=name, args=args)
                    return result
                log_event("confirm_declined", tool=name, args=args)
                return "User declined this action."

            result = await asyncio.to_thread(call_tool, name, args)
            flagged, matched = scan_injection(result)
            if flagged:
                log_event("injection_detected", tool=name, matched=matched)
                return f"[INJECTION WARNING] content withheld ({matched})"
            return result

        parsed_calls = []
        for call in calls:
            fn = call.get("function") or {}
            name = fn.get("name")
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            if name:
                parsed_calls.append((name, args))

        if not parsed_calls:
            continue

        # Multitasking: independent non-destructive calls run in
        # parallel. Destructive calls stay sequential so confirmation
        # prompts remain ordered and auditable.
        has_destructive = any(is_destructive(n) for n, _ in parsed_calls)
        max_parallel = max(1, int(getattr(settings, "MAX_PARALLEL_TOOLS", 4)))

        if len(parsed_calls) > 1 and not has_destructive:
            sem = asyncio.Semaphore(max_parallel)

            async def _guarded(n, a):
                async with sem:
                    return await _execute_tool_call(n, a)

            results = await asyncio.gather(
                *(_guarded(n, a) for n, a in parsed_calls)
            )
        else:
            results = []
            for n, a in parsed_calls:
                results.append(await _execute_tool_call(n, a))

        for (name, args), result in zip(parsed_calls, results):
            safe_args = {
                k: (redact_log(v) if isinstance(v, str) else v)
                for k, v in (args or {}).items()
            }
            log_event("tool_call", tool=name, args=safe_args, result=result[:200])
            log.append({"tool": name, "arguments": safe_args,
                        "result": result[:500]})
            _note_tool_call(session_id, name, args, result)

            _safe_result = result.replace(
                "<<END_UNTRUSTED_TOOL_RESULT", "<<_E_UTR_"
            ).replace(
                "<<UNTRUSTED_TOOL_RESULT", "<<_U_UTR_"
            )
            wrapped = (
                f"<<UNTRUSTED_TOOL_RESULT tool={name}>>\\n"
                f"{_safe_result}\\n"
                f"<<END_UNTRUSTED_TOOL_RESULT>>"
            )
            messages.append({
                "role": "tool",
                "tool_name": name,
                "name": name,
                "content": wrapped,
            })
'''
        src = src[:start] + new_block + src[end:]
        AGENT.write_text(src, encoding="utf-8")
        print("OK agent.py: parallel tool execution")

print("\nDone. Review diff with: git diff")
