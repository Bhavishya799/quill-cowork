"""patch_router.py - insert broad web_search detection into filter_tools.

Inserts a small block right before "# ---- Filesystem ----" inside
filter_tools. That comment is a stable anchor from the original file.
The block adds three new router rules for phrases the existing rules
miss:

    "search X"                 leading verb
    "search about X"           verb + preposition
    "google X" / "look up X"   leading verb

Guard: if the message mentions codebase/repo/file/code, the block
does not fire (so "search the codebase for TODO" still routes to
codebase_search).

Run from D:\\Quill-Cowork:  python patch_router.py
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).parent.resolve()
AGENT = ROOT / "backend" / "agent.py"

if not AGENT.exists():
    print(f"ERROR: {AGENT} not found")
    sys.exit(1)

src = AGENT.read_text(encoding="utf-8")

if "# broadened web_search detection" in src:
    print("[SKIP] router already patched")
    sys.exit(0)

anchor = "    # ---- Filesystem ----"
if anchor not in src:
    print("ERROR: could not find anchor '# ---- Filesystem ----'")
    print("       open backend/agent.py, search for 'Filesystem', paste")
    print("       the surrounding 5 lines.")
    sys.exit(1)

insert = (
    '    # broadened web_search detection (patch_router.py)\n'
    '    _code_ctx = re.search(\n'
    '        r"\\b(codebase|repo|repository|code|project|function|class|file|files)\\b",\n'
    '        m,\n'
    '    )\n'
    '    if not _code_ctx:\n'
    '        if re.match(\n'
    '            r"^\\s*(?:please\\s+|can\\s+you\\s+|could\\s+you\\s+)?'
    '(?:search|google|look\\s*up|research)\\b",\n'
    '            m,\n'
    '        ):\n'
    '            keep.add("web_search")\n'
    '        elif re.search(r"\\b(?:search|google|look\\s*up|research)\\s+(?:for|about|on)\\b", m):\n'
    '            keep.add("web_search")\n'
    '\n'
)

src = src.replace(anchor, insert + anchor, 1)
AGENT.write_text(src, encoding="utf-8")
print("[OK] inserted router block before '# ---- Filesystem ----'")


# --- Verify ---
print()
print("=" * 60)
print("Router test")
print("=" * 60)

r = subprocess.run(
    [sys.executable, "-c", """
import sys
sys.path.insert(0, 'backend')
import agent
from tools.registry import get_ollama_tools
agent.load_all_tools()
tools = get_ollama_tools()
tests = [
    ("search about the new odyssey movie", True),
    ("search about th new odyssey movie", True),
    ("search the web for the Python 3.13 release notes", True),
    ("google the latest AI developments", True),
    ("look up recent news about AMD GPUs", True),
    ("search for the best coffee shops in Kolkata", True),
    ("research the current state of fusion energy", True),
    ("what's the latest news about Nvidia", True),
    ("hello", False),
    ("list my workspace files", False),
    ("search the codebase for TODO", False),
    ("grep for 'def main' in the codebase", False),
]
pass_count = 0
for prompt, want in tests:
    names = [x["function"]["name"] for x in agent.filter_tools(prompt, tools)]
    got = "web_search" in names
    ok = (got == want)
    mark = "OK  " if ok else "FAIL"
    if ok: pass_count += 1
    print(f"  {mark} {prompt[:52]:52s} -> web_search={got}")
print()
print(f"  passed: {pass_count}/{len(tests)}")
""".strip()],
    cwd=str(ROOT), capture_output=True, text=True,
)

for line in (r.stdout or "").splitlines():
    print(line)
if r.returncode != 0:
    print("  [FAIL] import error")
    for line in (r.stderr or "").strip().splitlines()[-6:]:
        print("  " + line)

print()
print("=" * 60)
print("Next:")
print("  1. Restart the server: python backend\\main.py")
print("  2. Hard-reload: Ctrl+Shift+R")
print("  3. Ask: 'search about the new odyssey movie'")
print("=" * 60)