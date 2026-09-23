"""End-to-end latency — simple, single-tool, multi-tool."""

import httpx
import time
import statistics
import json
from datetime import datetime

BACKEND = "http://localhost:8000"

TESTS = [
    ("simple",      "Say hi in three words"),
    ("single_tool", "List my workspace files"),
    ("multi_tool",  "Read readme.txt and notes.txt, then summarize both"),
]


def measure(prompt, runs=3):
    times = []
    for _ in range(runs):
        start = time.time()
        httpx.post(
            f"{BACKEND}/chat",
            json={"message": prompt, "session_id": "lat"},
            timeout=180,
        )
        times.append(time.time() - start)
    return times


def main():
    print("=" * 60)
    print("LATENCY RESULTS")
    print("=" * 60)

    results = {}
    for label, prompt in TESTS:
        times = measure(prompt)
        median = statistics.median(times)
        results[label] = {
            "median": round(median, 2),
            "min": round(min(times), 2),
            "max": round(max(times), 2),
        }
        print(f"\n{label}:")
        print(f"  Median: {median:.2f}s")
        print(f"  Min:    {min(times):.2f}s")
        print(f"  Max:    {max(times):.2f}s")

    with open("latency_results.json", "w") as f:
        json.dump({"results": results, "timestamp": datetime.now().isoformat()}, f, indent=2)
    print("\nSaved to latency_results.json")


if __name__ == "__main__":
    main()