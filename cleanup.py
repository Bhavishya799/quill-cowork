"""cleanup.py - delete one-shot scripts, backups, pycache.

Only deletes files by explicit name. Never uses wildcards.
Does NOT commit. Prints next steps at the end.

Run from D:\\Quill-Cowork:  python cleanup.py
"""
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).parent.resolve()

if not (ROOT / ".git").is_dir():
    print(f"ERROR: {ROOT} is not a git repo")
    sys.exit(1)


def git(*args):
    r = subprocess.run(["git"] + list(args), cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8")
    return r.returncode, r.stdout, r.stderr


def is_tracked(rel):
    rc, _, _ = git("ls-files", "--error-unmatch", rel)
    return rc == 0


# One-shot scripts (repo owner's earlier fixes + this session's patches)
DEBRIS_FILES = [
    # repo owner's local-only scripts
    "fix_quill.py",
    "fix_github.py",
    "fix_filter.py",
    "fix_quill_codebase_summary.py",
    "fix_quill_spiral.py",
    "check_filter.py",
    "show_fails.py",
    "strip_slop.py",
    "dump_all.py",
    "make_dump.py",
    "watch_dump.py",
    "rebuild_frontend.py",
    # this session's patch scripts (already applied)
    "apply_audio.py",
    "apply_history.py",
    "apply_audio_v2.py",
    "wire_audio.py",
    "fix_wire.py",
    "strip_inline_audio.py",
    "finalize_audio.py",
    "write_audio.py",
    "restore_and_fix.py",
    # backups
    "backend/agent.py.bak",
    # archives / dumps
    "backend.tar.gz",
    "codebase_dump.txt",
    "codebase_full_dump.txt",
    "mycodebase.txt",
]

# Regeneratable directories
DEBRIS_DIRS = [
    "__pycache__",
    "backend/__pycache__",
    "backend/tools/__pycache__",
    "backend/providers/__pycache__",
    "backend/quill_core/__pycache__",
    "evaluation/__pycache__",
]

removed = []
skipped = []

for rel in DEBRIS_FILES:
    p = ROOT / rel
    if not p.exists():
        skipped.append(rel)
        continue
    if is_tracked(rel):
        rc, _, err = git("rm", "-f", rel)
        if rc == 0:
            removed.append(rel + "  (git rm)")
        else:
            print(f"[WARN] git rm {rel}: {err.strip()}")
    else:
        try:
            p.unlink()
            removed.append(rel)
        except Exception as e:
            print(f"[WARN] {rel}: {e}")

for rel in DEBRIS_DIRS:
    p = ROOT / rel
    if p.is_dir():
        try:
            shutil.rmtree(p)
            removed.append(rel + "/  (pycache)")
        except Exception as e:
            print(f"[WARN] {rel}: {e}")

# --- Report ---
print()
print("=" * 60)
print(f"cleanup.py - removed {len(removed)} items")
print("=" * 60)
for r in removed:
    print(f"  - {r}")
if skipped:
    print()
    print(f"  skipped {len(skipped)} not present")
print("=" * 60)

# --- Verify essentials intact ---
ESSENTIALS = [
    "backend/main.py",
    "backend/agent.py",
    "backend/audio.py",
    "backend/chat_store.py",
    "backend/config.py",
    "backend/safety.py",
    "backend/static/index.html",
    "backend/static/audio.js",
    "backend/requirements.txt",
    "backend/.env.example",
    "evaluation/bench_v3.py",
    "evaluation/test_cases_v3.py",
    "README.md",
    "SECURITY.md",
    "LICENSE",
]
print()
print("Essential files:")
missing = []
for rel in ESSENTIALS:
    p = ROOT / rel
    ok = p.exists()
    if not ok:
        missing.append(rel)
    size = p.stat().st_size if ok else 0
    print(f"  [{'OK  ' if ok else 'MISS'}] {rel}  ({size} bytes)")

# --- Verify imports ---
print()
print("Import check:")
r = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0,'backend'); "
     "import main, agent, audio, chat_store, config, safety; "
     "print('OK')"],
    cwd=str(ROOT), capture_output=True, text=True,
)
if r.returncode == 0 and "OK" in r.stdout:
    print("  [OK  ] backend modules import cleanly")
else:
    print("  [FAIL] import error:")
    print("    " + (r.stderr or r.stdout).strip().splitlines()[-1]
          if (r.stderr or r.stdout) else "    unknown")

# --- Git status ---
rc, out, _ = git("status", "--short")
print()
print("git status --short:")
print(out or "  (clean)")

rc, out, _ = git("branch", "--show-current")
branch = out.strip() or "(detached)"
print()
print(f"current branch: {branch}")

print()
print("=" * 60)
print("Next steps:")
print("=" * 60)
if missing:
    print(f"  !! {len(missing)} essential file(s) missing. Do not commit.")
    for m in missing:
        print(f"     - {m}")
else:
    print("  1. Smoke test:")
    print("       python backend\\main.py")
    print("     then Ctrl+Shift+R in the browser")
    print()
    print("  2. Commit the cleanup:")
    print("       git add -A")
    print("       git commit -m \"chore: remove one-shot scripts, backups, pycache\"")
    print()
    if branch == "main":
        print("  3. Push:")
        print("       git push origin main")
    else:
        print("  3. Merge to main and push:")
        print(f"       git checkout main")
        print(f"       git merge --no-ff {branch} -m \"Merge {branch}\"")
        print(f"       git push origin main")
        print(f"       git push origin --delete {branch}")
print("=" * 60)