"""add_rule.py - insert TOOL RESULT RULE into SYSTEM_PROMPT_TOOLS.

Finds the assignment, then walks to the matching closing paren by
counting depth. Inserts the rule as the last line before the close.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).parent.resolve()
AGENT = ROOT / "backend" / "agent.py"

src = AGENT.read_text(encoding="utf-8")

if "Never claim you lack real-time access" in src:
    print("[SKIP] rule already present")
    sys.exit(0)

marker = "SYSTEM_PROMPT_TOOLS = ("
idx = src.find(marker)
if idx == -1:
    print("[FAIL] SYSTEM_PROMPT_TOOLS assignment not found")
    sys.exit(1)

# Walk forward from the open paren, counting depth.
open_idx = src.find("(", idx)
depth = 0
close_idx = -1
in_str = None
escape = False
i = open_idx
while i < len(src):
    c = src[i]
    if in_str:
        if escape:
            escape = False
        elif c == "\\":
            escape = True
        elif c == in_str:
            in_str = None
    else:
        if c in ('"', "'"):
            in_str = c
        elif c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                close_idx = i
                break
    i += 1

if close_idx == -1:
    print("[FAIL] could not find matching closing paren")
    sys.exit(1)

# Insert the rule just before close_idx. The line before close_idx ends
# with ")" typically preceded by a trailing string on its own line.
rule = (
    '\n'
    '    "\\n"\n'
    '    "TOOL RESULT RULE: If a tool result appears in the conversation "\n'
    '    "with status=succeeded, its content is your ground truth. Answer "\n'
    '    "from it. Never claim you lack real-time access, cannot browse "\n'
    '    "the web, or do not have current information when a successful "\n'
    '    "web_search result is present. The results ARE the current "\n'
    '    "information."\n'
)

src = src[:close_idx] + rule + src[close_idx:]
AGENT.write_text(src, encoding="utf-8")
print(f"[OK] rule inserted before char {close_idx}")


# --- Verify ---
print()
print("=" * 60)
print("Verification")
print("=" * 60)

r = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0,'backend'); "
     "import agent; "
     "print('rule in TOOLS:', 'Never claim you lack real-time access' in agent.SYSTEM_PROMPT_TOOLS); "
     "print('rule in CHAT:',  'Never claim you lack real-time access' in agent.SYSTEM_PROMPT_CHAT)"],
    cwd=str(ROOT), capture_output=True, text=True,
)
for line in (r.stdout or "").strip().splitlines():
    print(f"  {line}")
if r.returncode != 0:
    print("  [FAIL]")
    for line in (r.stderr or "").strip().splitlines()[-8:]:
        print("  " + line)