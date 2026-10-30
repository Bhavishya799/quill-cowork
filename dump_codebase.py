"""dump_codebase.py - write a complete codebase dump, excluding credentials."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
OUT = ROOT / "codebase_dump.txt"

SKIP_DIRS = {
    ".git", ".github", "venv", ".venv", "__pycache__", "node_modules",
    ".pytest_cache", "workspace", ".idea", ".vscode", "site-packages",
    "dist", "build", ".fix_backups", "ntfy", ".mypy_cache", ".ruff_cache",
    ".tox", ".eggs", "htmlcov", "coverage", "models", "clones", "codebases",
}

SKIP_FILES = {
    ".env", ".env.local", "vault.enc", "vault.enc.bak", "vault.enc.old",
    "vault.enc.tmp", "audit.log.jsonl", "chat.db", "chat.db-wal", "chat.db-shm",
    "model_selection.json", "mcp_servers.local.json", "mcp_servers.json",
    "ntfy-server.yml", "server-startup.log", "body.json",
    "codebase_dump.txt", "codebase_full_dump.txt", "codebase_dump.py",
    "dump.py", "dump_codebase.py", "dump_all.py", "package-lock.json", "yarn.lock",
}

SKIP_EXTS = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".onnx",
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
    ".mp4", ".mp3", ".wav", ".flac", ".webm",
    ".db", ".sqlite",
    ".log", ".bak",
}

SKIP_PREFIXES = (
    "apply_", "fix_", "recover_", "repair_", "patch_",
    "wire_", "strip_", "cleanup", "update_docs", "restore_",
    "write_audio", "finalize_audio",
)


def is_binary(path):
    try:
        chunk = path.read_bytes()[:4096]
    except Exception:
        return True
    return b"\x00" in chunk


def should_skip_file(path):
    name = path.name
    if name in SKIP_FILES:
        return True
    if path.suffix.lower() in SKIP_EXTS:
        return True
    if any(name.startswith(p) for p in SKIP_PREFIXES):
        return True
    if name.endswith(".min.js") or name.endswith(".min.css"):
        return True
    return False


def should_skip_dir(name):
    return name in SKIP_DIRS or name.startswith(".")


files = []
excluded = []
for dirpath, dirnames, filenames in os.walk(ROOT):
    dirnames[:] = [d for d in dirnames if not should_skip_dir(d)]
    for f in filenames:
        p = Path(dirpath) / f
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        if should_skip_file(p):
            excluded.append(rel)
            continue
        if is_binary(p):
            excluded.append(rel + "  (binary)")
            continue
        files.append((rel, p))

files.sort(key=lambda x: x[0])

import datetime
lines = [
    "# Codebase Dump",
    "# Repo: Bhavishya799/quill-cowork",
    "# Files: " + str(len(files)),
    "# Generated: " + datetime.datetime.now().isoformat(timespec="seconds"),
    "# Excluded: " + str(len(excluded)) + " files (credentials, binaries, one-shot scripts)",
    "",
    "=" * 72,
    "",
]

for rel, p in files:
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        if content.startswith("\ufeff"):
            content = content[1:]
        lines.append("===== " + rel + " =====")
        lines.append(content)
        lines.append("")
        lines.append("")
    except Exception as e:
        lines.append("===== " + rel + " =====")
        lines.append("[Error reading: " + str(e) + "]")
        lines.append("")

OUT.write_text("\n".join(lines), encoding="utf-8")

size = OUT.stat().st_size
print("Wrote " + str(OUT))
print("Files included: " + str(len(files)))
print("Size: " + format(size, ",") + " bytes (" + ("%.1f" % (size / 1024 / 1024)) + " MB)")

print("\n--- Included ---")
for rel, _ in files:
    print("  " + rel)

print("\n--- Excluded (" + str(len(excluded)) + ") ---")
for rel in excluded[:40]:
    print("  " + rel)
if len(excluded) > 40:
    print("  ... and " + str(len(excluded) - 40) + " more")

risky = [rel for rel, _ in files if any(t in rel for t in (
    ".env", "vault", "audit", "chat.db", "workspace", "secret",
))]
if risky:
    print("\nWARNING: possible credential files in dump:")
    for r in risky:
        print("  " + r)
else:
    print("\nClean: no credential-looking files in dump.")
