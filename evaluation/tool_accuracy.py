"""Tool-selection accuracy evaluation.

Sends N prompts to the running backend, checks which tool the model
called, and reports whether it matches the expected tool.
Requires the server running on localhost:8000.
"""
import json
import sys
import time
from pathlib import Path

import httpx

API = "http://localhost:8000"
RESULTS = Path(__file__).parent / "tool_accuracy_results.json"


TEST_CASES = [
    # Filesystem
    ("list my workspace files", "list_directory", "filesystem"),
    ("what files are in the workspace", "list_directory", "filesystem"),
    ("read notes.txt", "read_file", "filesystem"),
    ("show me the contents of readme.txt", "read_file", "filesystem"),
    ("find all .py files in the workspace", "search_files", "filesystem"),
    ("write hello to test.txt", "write_file", "filesystem"),
    ("create a file called output.md with the text hi", "write_file", "filesystem"),
    # GitHub
    ("list my github repos", "list_repos", "github"),
    ("what repositories do I have", "list_repos", "github"),
    ("check my github notifications", "list_notifications", "github"),
    ("any unread github notifications", "list_notifications", "github"),
    ("list recent commits", "list_commits", "github"),
    ("mark all notifications as read", "mark_all_notifications_read", "github"),
    # Web / Wikipedia
    ("search the web for quantum computing news", "web_search", "web"),
    ("look up the Fermi paradox", "search_wikipedia", "web"),
    ("what does wikipedia say about the Battle of Hastings", "get_wikipedia_article", "web"),
    # Codebase
    ("list my connected codebases", "list_codebases", "codebase"),
    ("show me the tree of my codebase", "codebase_tree", "codebase"),
    ("find the authenticate function", "codebase_find_symbol", "codebase"),
    # Email
    ("list my last 5 emails", "list_emails", "email"),
    ("what's in my inbox", "list_emails", "email"),
    ("send an email to test@example.com saying hello", "send_email", "email"),
    # Conversational — should NOT call a tool
    ("hello", None, "conversational"),
    ("what is 2 + 2", None, "conversational"),
]


def _send(message: str, session_id: str):
    r = httpx.post(
        f"{API}/chat",
        json={"message": message, "session_id": session_id},
        timeout=180,
    )
    r.raise_for_status()
    return r.json()


def main():
    print("=" * 60)
    print("TOOL-SELECTION ACCURACY EVALUATION")
    print(f"  Server: {API}")
    print(f"  Cases:  {len(TEST_CASES)}")
    print("=" * 60)
    print()

    try:
        httpx.get(f"{API}/health", timeout=5).raise_for_status()
    except Exception as e:
        print(f"Server not reachable: {e}")
        sys.exit(1)
        
    httpx.post(f"{API}/models/slots/select", json={"slot": "balanced"}).raise_for_status()
    print("  Model locked to slot: balanced")
    print()
    total = len(TEST_CASES)
    correct = 0
    results = []

    for i, (prompt, expected, cat) in enumerate(TEST_CASES, 1):
        t0 = time.time()
        run_id = int(time.time())
        try:
            resp = _send(prompt, f"eval-{run_id}-{i}")
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

        print(f"  [{i:02d}/{total}] [{mark}] {prompt[:55]:55s} -> {actual or '(none)'}"
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