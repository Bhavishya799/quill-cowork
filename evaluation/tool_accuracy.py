"""Tool-selection accuracy evaluation — expanded to N=60.

10 prompts per category across 6 categories. Each prompt runs in a fresh
session. Model locked to balanced slot before the run.
"""
import json
import sys
import time
from pathlib import Path

import httpx

API = "http://localhost:8000"
RESULTS = Path(__file__).parent / "tool_accuracy_v2_results.json"


TEST_CASES = [
    # ------------------------------------------------------------------
    # Filesystem (10)
    # ------------------------------------------------------------------
    ("list my workspace files", "list_directory", "filesystem"),
    ("what files are in the workspace", "list_directory", "filesystem"),
    ("show me the files in the workspace root", "list_directory", "filesystem"),
    ("list the folder structure", "list_directory", "filesystem"),
    ("read notes.txt", "read_file", "filesystem"),
    ("show me the contents of readme.txt", "read_file", "filesystem"),
    ("open the file test.txt", "read_file", "filesystem"),
    ("find all .py files in the workspace", "search_files", "filesystem"),
    ("search for markdown files", "search_files", "filesystem"),
    ("write hello to output.txt", "write_file", "filesystem"),

    # ------------------------------------------------------------------
    # GitHub (10)
    # ------------------------------------------------------------------
    ("list my github repos", "list_repos", "github"),
    ("what repositories do I have", "list_repos", "github"),
    ("show my github repositories", "list_repos", "github"),
    ("check my github notifications", "list_notifications", "github"),
    ("any unread github notifications", "list_notifications", "github"),
    ("what's new on github", "list_notifications", "github"),
    ("list recent commits", "list_commits", "github"),
    ("show me the commits on main", "list_commits", "github"),
    ("mark all notifications as read", "mark_all_notifications_read", "github"),
    ("list open issues", "list_issues", "github"),

    # ------------------------------------------------------------------
    # Web + Wikipedia (10)
    # ------------------------------------------------------------------
    ("search the web for quantum computing news", "web_search", "web"),
    ("google the latest AI developments", "web_search", "web"),
    ("look up recent news about AMD GPUs", "web_search", "web"),
    ("search the web for python tutorials", "web_search", "web"),
    ("look up the Fermi paradox on wikipedia", "search_wikipedia", "web"),
    ("search wikipedia for quantum computing", "search_wikipedia", "web"),
    ("what does wikipedia say about the Battle of Hastings", "get_wikipedia_article", "web"),
    ("read the wikipedia article about Alan Turing", "get_wikipedia_article", "web"),
    ("fetch the page at https://example.com", "fetch_page", "web"),
    ("download the contents of that URL", "fetch_page", "web"),

    # ------------------------------------------------------------------
    # Codebase (10)
    # ------------------------------------------------------------------
    ("list my connected codebases", "list_codebases", "codebase"),
    ("what codebases are connected", "list_codebases", "codebase"),
    ("show me the tree of my codebase", "codebase_tree", "codebase"),
    ("what files are in the codebase", "codebase_tree", "codebase"),
    ("find the authenticate function", "codebase_find_symbol", "codebase"),
    ("where is the User class defined", "codebase_find_symbol", "codebase"),
    ("list all functions in the codebase", "codebase_symbols", "codebase"),
    ("search the codebase for 'TODO'", "codebase_search", "codebase"),
    ("read the file backend/main.py", "codebase_read", "codebase"),
    ("what does backend/agent.py import", "codebase_imports", "codebase"),

    # ------------------------------------------------------------------
    # Email (10)
    # ------------------------------------------------------------------
    ("list my last 5 emails", "list_emails", "email"),
    ("what's in my inbox", "list_emails", "email"),
    ("show me my recent emails", "list_emails", "email"),
    ("any unread emails", "list_emails", "email"),
    ("send an email to test@example.com saying hello", "send_email", "email"),
    ("email my team about the meeting", "send_email", "email"),
    ("create a draft reply to the last email", "create_draft", "email"),
    ("save a draft email to my boss", "create_draft", "email"),
    ("reply to the last email", "reply_to_email", "email"),
    ("read the email from alice", "get_email", "email"),

    # ------------------------------------------------------------------
    # Conversational — should NOT call any tool (10)
    # ------------------------------------------------------------------
    ("hello", None, "conversational"),
    ("what is 2 + 2", None, "conversational"),
    ("tell me a joke", None, "conversational"),
    ("how are you", None, "conversational"),
    ("what's the capital of France", None, "conversational"),
    ("explain how HTTPS works", None, "conversational"),
    ("write a short poem about autumn", None, "conversational"),
    ("what's a good name for a pet cat", None, "conversational"),
    ("summarize the concept of recursion", None, "conversational"),
    ("thanks", None, "conversational"),
]


def _send(message, session_id):
    r = httpx.post(f"{API}/chat",
                   json={"message": message, "session_id": session_id},
                   timeout=180)
    r.raise_for_status()
    return r.json()


def main():
    print("=" * 60)
    print("TOOL-SELECTION ACCURACY v2 (N=60)")
    print(f"  Server: {API}")
    print(f"  Cases:  {len(TEST_CASES)}")
    print("=" * 60)
    print()

    try:
        httpx.get(f"{API}/health", timeout=5).raise_for_status()
    except Exception as e:
        print(f"Server not reachable: {e}")
        sys.exit(1)

    httpx.post(f"{API}/models/slots/select",
               json={"slot": "balanced"}).raise_for_status()
    print("  Model locked to slot: balanced")
    print()

    total = len(TEST_CASES)
    correct = 0
    results = []
    run_id = int(time.time())

    for i, (prompt, expected, cat) in enumerate(TEST_CASES, 1):
        t0 = time.time()
        try:
            resp = _send(prompt, f"eval2-{run_id}-{i}")
        except Exception as e:
            print(f"  [{i:02d}/{total}] ERROR: {e}")
            results.append({"prompt": prompt, "expected": expected,
                            "actual": "error", "category": cat,
                            "correct": False, "elapsed": 0})
            continue

        calls = resp.get("tool_calls") or []
        actual = calls[0]["tool"] if calls else None
        ok = (actual == expected)
        if ok:
            correct += 1
            mark = "OK  "
        else:
            mark = "FAIL"

        print(f"  [{i:02d}/{total}] [{mark}] {prompt[:52]:52s} -> {actual or '(none)'}"
              f"  (expected {expected or '(none)'})")

        results.append({
            "prompt": prompt,
            "expected": expected,
            "actual": actual,
            "category": cat,
            "correct": ok,
            "elapsed": round(time.time() - t0, 2),
        })

    accuracy = correct / total if total else 0
    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    print(f"  Overall: {correct}/{total}  ({accuracy:.1%})")
    print()

    cats = {}
    for r in results:
        c = r["category"]
        cats.setdefault(c, {"correct": 0, "total": 0})
        cats[c]["total"] += 1
        if r["correct"]:
            cats[c]["correct"] += 1

    print("  By category:")
    for c, s in sorted(cats.items()):
        pct = s["correct"] / s["total"] * 100
        print(f"    {c:16s}  {s['correct']:2d}/{s['total']:2d}  ({pct:.0f}%)")

    out = {
        "total": total,
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "by_category": cats,
        "results": results,
    }
    RESULTS.write_text(json.dumps(out, indent=2))
    print()
    print(f"Saved: {RESULTS}")


if __name__ == "__main__":
    main()