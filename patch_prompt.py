"""patch_prompt.py - force tool use on imperative search phrasings.

Root cause: the router now offers web_search, but the 4B model still
answers from memory because (a) the tool description is generic and
(b) the system prompt gives it an escape hatch ("if no tool fits,
answer in prose").

Fix:
  1. Rewrite the web_search docstring to be directive.
  2. Add a "TOOL-FIRST RULE" to SYSTEM_PROMPT.

Run from D:\\Quill-Cowork:  python patch_prompt.py
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).parent.resolve()
BACKEND = ROOT / "backend"
AGENT = BACKEND / "agent.py"
SEARCH = BACKEND / "tools" / "search.py"

for p in (AGENT, SEARCH):
    if not p.exists():
        print(f"ERROR: {p} not found")
        sys.exit(1)

changed = []

# =====================================================================
# 1. web_search docstring
# =====================================================================
src = SEARCH.read_text(encoding="utf-8")

old_doc = '''@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web. Returns titles, URLs, and short snippets."""
    return format_results(search_structured(query, max_results))'''

new_doc = '''@tool
def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web. ALWAYS call this when the user asks you
    to search, google, look up, research, or find information about
    anything current, recent, or factual you cannot verify. Do NOT
    answer from memory if the user's request is phrased as a search
    instruction. Returns titles, URLs, and short snippets."""
    return format_results(search_structured(query, max_results))'''

if old_doc in src:
    src = src.replace(old_doc, new_doc, 1)
    SEARCH.write_text(src, encoding="utf-8")
    changed.append("search.py: directive docstring")
    print("[OK] search.py: directive docstring")
elif "ALWAYS call this when the user asks" in src:
    print("[SKIP] search.py: already directive")
else:
    print("[WARN] search.py: anchor not found, skipping")


# =====================================================================
# 2. SYSTEM_PROMPT rule
# =====================================================================
src = AGENT.read_text(encoding="utf-8")

if "TOOL-FIRST RULE" in src:
    print("[SKIP] agent.py: rule already present")
else:
    # Find the closing of SYSTEM_PROMPT. It ends with a string then ).
    # Look for the last sentence of the prompt before the closing paren.
    anchors = [
        '"Never describe a tool call in words -- either call it or don\'t."',
        '"Never describe a tool call in words -- either call it or don\'t."\n)',
    ]
    hit = None
    for a in anchors:
        if a in src:
            hit = a
            break

    if hit is None:
        print("[WARN] agent.py: SYSTEM_PROMPT anchor not found")
        print("       open backend/agent.py, find the SYSTEM_PROMPT block,")
        print("       paste the last 3 lines to me.")
    else:
        addition = (
            '"\\n"\n'
            '    "TOOL-FIRST RULE: If the user\'s message begins with an "\n'
            '    "imperative verb like search, google, look up, research, "\n'
            '    "find, fetch, check, get, or list, you MUST call the "\n'
            '    "corresponding tool in this turn. Do not answer from "\n'
            '    "memory. Do not say you cannot access the internet. The "\n'
            '    "tool is available -- call it."\n'
            ')'
        )
        # Replace the anchor with anchor-minus-closing-paren + addition
        # Only if the anchor text is followed by ).
        if hit == anchors[0] and ')\n' in src[src.find(hit):src.find(hit)+200]:
            # Find the closing paren after the anchor
            idx = src.find(hit)
            end = src.find(")", idx)
            # Replace the anchor text with the anchor text, then the addition
            new_block = (hit + "\n"
                         '    "\\n"\n'
                         '    "TOOL-FIRST RULE: If the user\'s message begins with an "\n'
                         '    "imperative verb like search, google, look up, research, "\n'
                         '    "find, fetch, check, get, or list, you MUST call the "\n'
                         '    "corresponding tool in this turn. Do not answer from "\n'
                         '    "memory. Do not say you cannot access the internet. The "\n'
                         '    "tool is available -- call it."\n'
                         ')')
            src = src[:idx] + new_block + src[end+1:]
            AGENT.write_text(src, encoding="utf-8")
            changed.append("agent.py: TOOL-FIRST RULE")
            print("[OK] agent.py: TOOL-FIRST RULE added")
        else:
            print("[WARN] agent.py: could not locate closing paren")
            print("       open backend/agent.py, find the SYSTEM_PROMPT block,")
            print("       paste the last 5 lines to me.")


# =====================================================================
# 3. Verify
# =====================================================================
print()
print("=" * 60)
print("Verification")
print("=" * 60)

check = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0,'backend'); "
     "import agent; "
     "src = agent.SYSTEM_PROMPT; "
     "print('system_prompt_len:', len(src)); "
     "print('has_rule:', 'TOOL-FIRST RULE' in src); "
     "print('has_search_word:', 'search' in src.lower()); "
     "import tools.search; "
     "d = tools.search.web_search.__doc__ or ''; "
     "print('doc_has_always:', 'ALWAYS' in d)"],
    cwd=str(ROOT), capture_output=True, text=True,
)
for line in (check.stdout or "").strip().splitlines():
    print(f"  {line}")
if check.returncode != 0:
    print("  [FAIL] import error")
    for line in (check.stderr or "").strip().splitlines()[-6:]:
        print("  " + line)

print()
print("=" * 60)
print("Next:")
print("  1. Restart: python backend\\main.py")
print("  2. Hard-reload: Ctrl+Shift+R")
print("  3. Ask: 'search about the new odyssey movie'")
print("  4. Console should show:")
print("       [search] search_start ...")
print("       [search] card created ...")
print("=" * 60)