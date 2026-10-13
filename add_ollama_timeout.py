"""add_ollama_timeout.py - add a timeout to the ollama.chat call.

Turns an infinite hang into an exception the retry loop can handle,
so the user sees an error instead of the typing animation forever.
"""
from pathlib import Path
import re

p = Path("backend/providers/ollama_provider.py")
src = p.read_text(encoding="utf-8")

if "timeout=" in src and "OLLAMA_TIMEOUT" in src:
    print("[SKIP] already patched")
    raise SystemExit(0)

# Add OLLAMA_TIMEOUT default in __init__
old_init = '''    def __init__(self):
        self.default_model = os.getenv("OLLAMA_MODEL", "quill")
        self.client = ollama.Client(
            host=os.getenv("OLLAMA_HOST", "http://localhost:11434")
        )'''
new_init = '''    def __init__(self):
        self.default_model = os.getenv("OLLAMA_MODEL", "quill")
        try:
            self.timeout = float(os.getenv("OLLAMA_TIMEOUT", "120"))
        except ValueError:
            self.timeout = 120.0
        self.client = ollama.Client(
            host=os.getenv("OLLAMA_HOST", "http://localhost:11434")
        )'''

if old_init in src:
    src = src.replace(old_init, new_init, 1)
    print("[OK] init: OLLAMA_TIMEOUT env var (default 120s)")
else:
    print("[WARN] init anchor not found; add OLLAMA_TIMEOUT manually")

# Add timeout= to the chat call
old_chat = '''                response = self.client.chat(
                    model=model or self.default_model,
                    messages=messages,
                    tools=tools or None,
                    think=False,'''
new_chat = '''                response = self.client.chat(
                    model=model or self.default_model,
                    messages=messages,
                    tools=tools or None,
                    think=False,
                    timeout=self.timeout,'''

if old_chat in src:
    src = src.replace(old_chat, new_chat, 1)
    print("[OK] chat: timeout=self.timeout")
else:
    # Try a more permissive match
    src2 = re.sub(
        r"(response = self\.client\.chat\(\n(?:\s+.+\n)+?)(\s+)\)",
        lambda m: m.group(1) + "                    timeout=self.timeout,\n" + m.group(2) + ")",
        src, count=1,
    )
    if src2 != src:
        src = src2
        print("[OK] chat: timeout added via regex")
    else:
        print("[WARN] could not find chat call to patch")

p.write_text(src, encoding="utf-8")
print()
print("Verify:")
print("  python -c \"import sys; sys.path.insert(0,'backend'); from providers import get_provider; p=get_provider(); print('timeout:', p.timeout)\"")