"""Tool-selection accuracy + latency benchmark for Quill-Cowork.

Requires the backend running at http://localhost:8000.

Usage:
    python evaluation/bench_v3.py
    python evaluation/bench_v3.py --runs 3
    python evaluation/bench_v3.py --category codebase
    python evaluation/bench_v3.py --no-latency
"""
import argparse
import json
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from test_cases_v3 import accuracy_cases

API = "http://localhost:8000"
OUT = Path(__file__).parent / "bench_v3_results.json"


def send(prompt, sid, timeout=180):
    t0 = time.time()
    try:
        r = httpx.post(f"{API}/chat",
                       json={"message": prompt, "session_id": sid},
                       timeout=timeout)
        r.raise_for_status()
        return time.time() - t0, r.json(), None
    except Exception as e:
        return time.time() - t0, None, str(e)


def first_tool(resp):
    calls = (resp or {}).get("tool_calls") or []
    return calls[0]["tool"] if calls else None


def check_server():
    try:
        httpx.get(f"{API}/health", timeout=5).raise_for_status()
        return True
    except Exception as e:
        print(f"Server not reachable at {API}: {e}")
        print("Start it with:  python backend/main.py")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--category", default=None)
    ap.add_argument("--no-latency", action="store_true")
    args = ap.parse_args()

    if not check_server():
        sys.exit(1)

    cases = accuracy_cases()
    if args.category:
        cases = [c for c in cases if c[2] == args.category]

    print("=" * 72)
    print(f"TOOL-SELECTION BENCHMARK  ({len(cases)} cases x {args.runs} runs)")
    print("=" * 72)

    run_id = int(time.time())
    per_case = []
    by_cat = defaultdict(lambda: {"correct": 0, "total": 0, "latencies": []})
    hallucinated = 0

    for i, (prompt, expected, cat, notes) in enumerate(cases, 1):
        correct_runs = 0
        latencies = []
        last_actual = None
        last_err = None

        for r in range(args.runs):
            sid = f"bench-{run_id}-{i}-{r}"
            elapsed, resp, err = send(prompt, sid)
            if err:
                last_err = err
                continue
            latencies.append(elapsed)
            actual = first_tool(resp)
            last_actual = actual
            if expected is None:
                if actual is None:
                    correct_runs += 1
                else:
                    hallucinated += 1
            elif actual == expected:
                correct_runs += 1

        ok = correct_runs == args.runs and args.runs > 0
        by_cat[cat]["total"] += args.runs
        by_cat[cat]["correct"] += correct_runs
        by_cat[cat]["latencies"].extend(latencies)

        per_case.append({
            "prompt": prompt,
            "expected": expected,
            "actual": last_actual,
            "category": cat,
            "notes": notes,
            "correct_runs": correct_runs,
            "runs": args.runs,
            "latencies": [round(x, 2) for x in latencies],
            "error": last_err,
        })

        mark = "OK  " if ok else "FAIL"
        got = last_actual if last_actual else "(none)"
        exp = expected if expected else "(none)"
        print(f"  [{i:03d}/{len(cases):03d}] [{mark}] {cat:14s} "
              f"{prompt[:50]:50s} -> {got:22s} (exp {exp})")

    total_correct = sum(v["correct"] for v in by_cat.values())
    total_runs = sum(v["total"] for v in by_cat.values())
    overall = total_correct / total_runs if total_runs else 0

    print()
    print("=" * 72)
    print("RESULTS")
    print("=" * 72)
    print(f"  Overall accuracy: {total_correct}/{total_runs}  ({overall:.1%})")
    print(f"  Tool hallucinations on conversational prompts: {hallucinated}")
    print()
    print("  By category:")
    for cat in sorted(by_cat):
        v = by_cat[cat]
        pct = v["correct"] / v["total"] * 100 if v["total"] else 0
        med = statistics.median(v["latencies"]) if v["latencies"] else 0
        print(f"    {cat:16s} {v['correct']:3d}/{v['total']:3d}  "
              f"({pct:5.1f}%)  median {med:6.2f}s")

    failures = [c for c in per_case if c["correct_runs"] < c["runs"]]
    if failures:
        print()
        print(f"  Failures ({len(failures)}):")
        for c in failures:
            print(f"    [{c['category']:14s}] {c['prompt'][:58]!r}")
            print(f"       got={c['actual']}  exp={c['expected']}  "
                  f"correct_runs={c['correct_runs']}/{c['runs']}")

    out = {
        "runs_per_case": args.runs,
        "total_cases": len(cases),
        "total_runs": total_runs,
        "overall_accuracy": round(overall, 4),
        "hallucinated_tool_calls": hallucinated,
        "by_category": {
            cat: {
                "correct": v["correct"],
                "total": v["total"],
                "median_latency_sec": round(statistics.median(v["latencies"]), 2)
                    if v["latencies"] else 0,
            }
            for cat, v in by_cat.items()
        },
        "cases": per_case,
    }
    OUT.write_text(json.dumps(out, indent=2))
    print()
    print(f"  Saved: {OUT}")

    if not args.no_latency:
        all_lat = [x for v in by_cat.values() for x in v["latencies"]]
        if all_lat:
            print()
            print("  Latency summary:")
            print(f"    median : {statistics.median(all_lat):6.2f}s")
            print(f"    mean   : {statistics.mean(all_lat):6.2f}s")
            print(f"    min    : {min(all_lat):6.2f}s")
            print(f"    max    : {max(all_lat):6.2f}s")
            p95_idx = int(len(all_lat) * 0.95)
            print(f"    p95    : {sorted(all_lat)[p95_idx]:6.2f}s")


if __name__ == "__main__":
    main()
