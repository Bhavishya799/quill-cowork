"""Latency evaluation with tool-call verification.

Measures wall-clock time for a set of prompts. Records which tools fired
so a tool-less run is not misreported as "fast."
"""
import json
import statistics
import time
from pathlib import Path

import httpx

API = "http://localhost:8000"
RESULTS = Path(__file__).parent / "latency_results.json"

PROMPTS = [
    ("conversational", "what is 2 + 2", None),
    ("filesystem", "list my workspace files", "list_directory"),
    ("github", "list my github repos", "list_repos"),
    ("web_search", "search the web for the latest AI news", "web_search"),
    ("wikipedia", "look up the Fermi paradox", "search_wikipedia"),
    ("codebase", "list my connected codebases", "list_codebases"),
]

RUNS = 3


def _time_one(prompt: str, sid: str):
    t0 = time.time()
    try:
        r = httpx.post(f"{API}/chat",
                       json={"message": prompt, "session_id": sid},
                       timeout=300)
        r.raise_for_status()
        elapsed = time.time() - t0
        data = r.json()
        calls = data.get("tool_calls") or []
        return elapsed, [c["tool"] for c in calls], None
    except Exception as e:
        return time.time() - t0, [], str(e)

    
def main():
    print("=" * 60)
    print("LATENCY EVALUATION")
    print(f"  Server: {API}")
    print(f"  Runs per prompt: {RUNS}")
    print("=" * 60)
    print()

    try:
        httpx.get(f"{API}/health", timeout=5).raise_for_status()
    except Exception as e:
        print(f"Server not reachable: {e}")
        return
        
            httpx.post(f"{API}/models/slots/select", json={"slot": "balanced"}).raise_for_status()
    print("  Model locked to slot: balanced")
    print()

    out = []
    for label, prompt, expected_tool in PROMPTS:
        times = []
        tools_seen = set()
        errors = 0
        for i in range(RUNS):
              elapsed, tools, err = _time_one(prompt, f"lat-{int(time.time())}-{label}-{i}")
            if err:
                errors += 1
                continue
            times.append(elapsed)
            tools_seen.update(tools)

        if times:
            med = statistics.median(times)
            mn = min(times)
            mx = max(times)
        else:
            med = mn = mx = 0

        verified = (expected_tool in tools_seen) if expected_tool else True
        flag = "" if verified else "  [TOOL MISMATCH]"
        print(f"  {label:14s}  median {med:6.2f}s  min {mn:6.2f}s  max {mx:6.2f}s"
              f"  tools={sorted(tools_seen) or ['(none)']}{flag}")

        out.append({
            "label": label,
            "prompt": prompt,
            "runs": RUNS,
            "errors": errors,
            "median_sec": round(med, 2),
            "min_sec": round(mn, 2),
            "max_sec": round(mx, 2),
            "tools_fired": sorted(tools_seen),
            "expected_tool": expected_tool,
            "tool_verified": verified,
        })

    RESULTS.write_text(json.dumps(out, indent=2))
    print()
    print(f"Saved: {RESULTS}")


if __name__ == "__main__":
    main()