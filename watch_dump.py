"""Quill-Cowork auto-dump watcher (polling). Regenerates
codebase_full_dump.txt whenever a tracked file changes. Ctrl+C to stop.
"""
import hashlib
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
OUT = ROOT / "codebase_full_dump.txt"
DUMP_SCRIPT = ROOT / "dump_all.py"
INTERVAL = 3

EXCLUDE_DIRS = {
    ".git", "venv", ".venv", "__pycache__", "node_modules",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    ".quill", "htmlcov",
}

SKIP_EXTS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".svg",
    ".mp3", ".mp4", ".mov", ".webm", ".wav", ".flac",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
}


def snapshot():
    h = hashlib.sha1()
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for f in sorted(filenames):
            p = Path(dirpath) / f
            if p == OUT:
                continue
            if p.suffix.lower() in SKIP_EXTS:
                continue
            try:
                st = p.stat()
                h.update(str(p.relative_to(ROOT)).encode("utf-8"))
                h.update(str(st.st_mtime_ns).encode("ascii"))
                h.update(str(st.st_size).encode("ascii"))
            except OSError:
                continue
    return h.hexdigest()


def regenerate():
    try:
        r = subprocess.run(
            [sys.executable, str(DUMP_SCRIPT), "--redact", "--out", str(OUT)],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if r.returncode != 0:
            print("  dump failed (exit %d): %s" % (r.returncode, r.stderr.strip()[:200]))
            return False
        kb = OUT.stat().st_size / 1024
        ts = time.strftime("%H:%M:%S")
        print("[%s] regenerated (%.1f KB)" % (ts, kb))
        return True
    except Exception as e:
        print("  dump error: %s" % e)
        return False


def main():
    if not DUMP_SCRIPT.exists():
        print("ERROR: %s not found" % DUMP_SCRIPT)
        sys.exit(1)

    print()
    print("  Quill-Cowork auto-dump watcher (polling)")
    print("  ----------------------------------------")
    print("  Root:      %s" % ROOT)
    print("  Output:    %s" % OUT)
    print("  Interval:  %ds" % INTERVAL)
    print()

    print("  Generating initial dump...")
    regenerate()

    last = snapshot()
    print()
    print("  Watching for changes. Ctrl+C to stop.")
    print()

    try:
        while True:
            time.sleep(INTERVAL)
            now = snapshot()
            if now != last:
                last = now
                regenerate()
    except KeyboardInterrupt:
        print()
        print("  Stopped.")


if __name__ == "__main__":
    main()
