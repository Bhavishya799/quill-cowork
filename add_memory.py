"""add_memory.py - semantic memory over chat history.

Adds a memories table to backend/workspace/.quill/chat.db, embeds
each user turn and short assistant reply using Ollama's
nomic-embed-text, and injects the top-k most relevant past turns
into the system prompt for the current message.

Requirements:
  ollama pull nomic-embed-text

If the embedding model is missing, memory silently disables and the
assistant works exactly as before. Chat history is unaffected.

Run from D:\\Quill-Cowork:  python add_memory.py
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).parent.resolve()
BACKEND = ROOT / "backend"

for f in ("agent.py", "main.py", "config.py", "chat_store.py"):
    if not (BACKEND / f).exists():
        print(f"ERROR: backend/{f} not found")
        sys.exit(1)

_log = []
def note(msg, kind="ok"):
    _log.append((msg, kind))
    tag = {"ok": "[OK]  ", "skip": "[SKIP]", "warn": "[WARN]"}.get(kind, "[?]   ")
    print(f"{tag} {msg}")


# =====================================================================
# 1. backend/memory.py
# =====================================================================
MEMORY_PY = r'''"""Semantic memory over chat history.

Stores per-turn embeddings in the same SQLite file as chat history
(chat.db), and retrieves the top-k relevant past turns for a query.

Design:
  - One embedding per user message and one per short assistant reply.
  - Skip greetings, very short text, and long assistant replies
    (they add noise more than signal).
  - Brute-force cosine similarity. Fine up to ~50k rows.
  - If the embedding model is unavailable, all functions no-op.

Env:
  MEMORY_ENABLED   1 | 0    (default 1)
  MEMORY_MODEL     Ollama embedding model (default nomic-embed-text)
  MEMORY_TOP_K     memories to inject per turn (default 5)
  MEMORY_MIN_SIM   cosine threshold (default 0.45)
"""
from __future__ import annotations

import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

# Reuse the chat DB so we have one file for all persistence.
DB_PATH = Path(__file__).parent / "workspace" / ".quill" / "chat.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_embed_lock = threading.Lock()
_embed_err: Optional[str] = None
_ready_checked = False


# ---------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------
def is_enabled() -> bool:
    return os.getenv("MEMORY_ENABLED", "1") not in ("0", "false", "False")


def _model_name() -> str:
    return (os.getenv("MEMORY_MODEL", "nomic-embed-text") or "nomic-embed-text").strip()


def _top_k() -> int:
    try:
        return max(1, int(os.getenv("MEMORY_TOP_K", "5")))
    except ValueError:
        return 5


def _min_sim() -> float:
    try:
        return float(os.getenv("MEMORY_MIN_SIM", "0.45"))
    except ValueError:
        return 0.45


# ---------------------------------------------------------------------
# DB
# ---------------------------------------------------------------------
_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id TEXT,
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  embedding BLOB NOT NULL,
  dim INTEGER NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_created
  ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_chat
  ON memories(chat_id);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=10)
    c.execute("PRAGMA journal_mode = WAL")
    return c


def init() -> None:
    with _lock, _conn() as c:
        c.executescript(_SCHEMA)


# ---------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------
def _embed_sync(text: str) -> Optional[List[float]]:
    global _embed_err, _ready_checked
    if not text:
        return None
    with _embed_lock:
        try:
            import ollama
            client = ollama.Client(
                host=os.getenv("OLLAMA_HOST", "http://localhost:11434")
            )
            model = _model_name()
            # Newer SDK: client.embed(model, input=...)
            if hasattr(client, "embed"):
                try:
                    r = client.embed(model=model, input=text)
                    vecs = r.get("embeddings") if isinstance(r, dict) else getattr(r, "embeddings", None)
                    if vecs:
                        _embed_err = None
                        return list(vecs[0])
                except Exception:
                    pass
            # Older SDK: client.embeddings(model, prompt=...)
            if hasattr(client, "embeddings"):
                r = client.embeddings(model=model, prompt=text)
                vec = r.get("embedding") if isinstance(r, dict) else getattr(r, "embedding", None)
                if vec:
                    _embed_err = None
                    return list(vec)
            _embed_err = "no embed method on ollama.Client"
            return None
        except Exception as e:
            _embed_err = f"{type(e).__name__}: {e}"
            return None


def embed(text: str) -> Optional[List[float]]:
    return _embed_sync(text)


def _to_blob(vec: List[float]) -> bytes:
    return np.asarray(vec, dtype=np.float32).tobytes()


def _from_blob(blob: bytes) -> np.ndarray:
    return np.frombuffer(blob, dtype=np.float32)


def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


# ---------------------------------------------------------------------
# Remember
# ---------------------------------------------------------------------
_GREETINGS = {"hi", "hello", "hey", "thanks", "thank you",
              "good morning", "good night", "bye", "ok", "okay"}


def _is_noise(text: str, role: str) -> bool:
    t = text.strip().lower()
    if len(t) < 10:
        return True
    if t in _GREETINGS:
        return True
    # Long assistant replies are usually walls of text the user just
    # asked for once. Not useful as memory.
    if role == "assistant" and len(text) > 600:
        return True
    return False


def remember(chat_id: str, role: str, text: str) -> bool:
    if not is_enabled():
        return False
    text = (text or "").strip()
    if not text:
        return False
    if _is_noise(text, role):
        return False
    if len(text) > 2000:
        text = text[:2000]

    init()

    # Skip exact duplicates (common with retries and copy-paste).
    with _lock:
        conn = _conn()
        try:
            row = conn.execute(
                "SELECT 1 FROM memories WHERE text = ? LIMIT 1", (text,)
            ).fetchone()
            if row:
                return False
        finally:
            conn.close()

    vec = embed(text)
    if not vec:
        return False

    blob = _to_blob(vec)
    with _lock:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO memories (chat_id, role, text, embedding, dim, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (chat_id, role, text, blob, len(vec), time.time()),
            )
            conn.commit()
        finally:
            conn.close()
    return True


# ---------------------------------------------------------------------
# Recall
# ---------------------------------------------------------------------
def recall(query: str, k: int = 5, exclude_chat: Optional[str] = None,
           min_similarity: Optional[float] = None) -> List[Dict]:
    if not is_enabled() or not query:
        return []
    q_vec = embed(query)
    if not q_vec:
        return []
    q = np.asarray(q_vec, dtype=np.float32)

    init()

    rows: List[tuple] = []
    with _lock:
        conn = _conn()
        try:
            cur = conn.execute(
                "SELECT id, chat_id, role, text, embedding, created_at "
                "FROM memories ORDER BY created_at DESC LIMIT 20000"
            )
            rows = cur.fetchall()
        finally:
            conn.close()

    if not rows:
        return []

    cutoff = min_similarity if min_similarity is not None else _min_sim()
    scored: List[tuple] = []
    for rid, cid, role, text, blob, ts in rows:
        if exclude_chat and cid == exclude_chat:
            continue
        try:
            v = _from_blob(blob)
        except Exception:
            continue
        if v.shape[0] != q.shape[0]:
            # Different embedding model than what's stored; skip.
            continue
        sim = _cosine(q, v)
        if sim >= cutoff:
            scored.append((sim, rid, cid, role, text, ts))

    scored.sort(key=lambda x: -x[0])
    top = scored[: max(1, k)]
    return [
        {"id": rid, "chat_id": cid, "role": role,
         "text": text, "similarity": round(sim, 3),
         "created_at": ts}
        for (sim, rid, cid, role, text, ts) in top
    ]


# ---------------------------------------------------------------------
# Format for prompt
# ---------------------------------------------------------------------
def _short_date(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return "?"


def format_for_prompt(query: str, session_id: str = "",
                      top_k: Optional[int] = None) -> str:
    if not is_enabled():
        return ""
    k = top_k or _top_k()
    hits = recall(query, k=k, exclude_chat=session_id or None)
    if not hits:
        return ""
    lines = [
        "Relevant context from past conversations (use only if helpful;",
        "do not explicitly reference this list to the user):",
    ]
    for h in hits:
        d = _short_date(h["created_at"])
        who = "User" if h["role"] == "user" else "You"
        txt = (h["text"] or "").replace("\n", " ").strip()[:200]
        lines.append(f'- [{d}] {who}: "{txt}"')
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Status / maintenance
# ---------------------------------------------------------------------
def status() -> dict:
    info = {
        "enabled": is_enabled(),
        "model": _model_name(),
        "top_k": _top_k(),
        "min_similarity": _min_sim(),
        "error": _embed_err,
    }
    try:
        init()
        with _lock:
            conn = _conn()
            try:
                row = conn.execute("SELECT COUNT(*) FROM memories").fetchone()
                info["count"] = int(row[0]) if row else 0
            finally:
                conn.close()
    except Exception as e:
        info["count"] = -1
        info["error"] = info.get("error") or f"{type(e).__name__}: {e}"
    return info


def clear() -> int:
    with _lock:
        conn = _conn()
        try:
            n = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            conn.execute("DELETE FROM memories")
            conn.commit()
            return int(n)
        finally:
            conn.close()
'''

mp = BACKEND / "memory.py"
if not mp.exists() or "class " not in mp.read_text(encoding="utf-8") or "def remember" not in mp.read_text(encoding="utf-8"):
    mp.write_text(MEMORY_PY, encoding="utf-8")
    note("wrote backend/memory.py")
else:
    note("backend/memory.py already present", "skip")


# =====================================================================
# 2. config.py - add memory env vars
# =====================================================================
CFG = BACKEND / "config.py"
src = CFG.read_text(encoding="utf-8")
if "MEMORY_ENABLED" not in src:
    anchor = '    MAX_PARALLEL_TOOLS = int(os.getenv("MAX_PARALLEL_TOOLS", "4"))\n'
    if anchor in src:
        addition = (
            anchor
            + '    MEMORY_ENABLED = os.getenv("MEMORY_ENABLED", "1")\n'
            + '    MEMORY_MODEL = os.getenv("MEMORY_MODEL", "nomic-embed-text")\n'
            + '    MEMORY_TOP_K = int(os.getenv("MEMORY_TOP_K", "5"))\n'
            + '    MEMORY_MIN_SIM = float(os.getenv("MEMORY_MIN_SIM", "0.45"))\n'
        )
        src = src.replace(anchor, addition, 1)
        CFG.write_text(src, encoding="utf-8")
        note("config.py: memory vars")
    else:
        note("config.py: MAX_PARALLEL_TOOLS anchor missing", "warn")
else:
    note("config.py: memory vars already present", "skip")


# =====================================================================
# 3. agent.py - recall + inject into system prompt
# =====================================================================
AGENT = BACKEND / "agent.py"
src = AGENT.read_text(encoding="utf-8")

if "format_for_prompt" not in src:
    # Anchor on the messages list construction, which is stable.
    anchor = "    messages: List[Dict[str, Any]] = ["
    if anchor in src:
        insert = (
            '    # Semantic memory: recall relevant past turns\n'
            '    try:\n'
            '        import memory as _mem\n'
            '        _mem_block = _mem.format_for_prompt(\n'
            '            user_message, session_id=session_id\n'
            '        )\n'
            '        if _mem_block:\n'
            '            system_content += "\\n\\n" + _mem_block\n'
            '    except Exception:\n'
            '        pass\n\n'
        )
        src = src.replace(anchor, insert + anchor, 1)
        AGENT.write_text(src, encoding="utf-8")
        note("agent.py: memory recall + inject before messages")
    else:
        note("agent.py: messages list anchor not found", "warn")
else:
    note("agent.py: memory already wired", "skip")


# =====================================================================
# 4. main.py - remember after each turn + endpoints
# =====================================================================
MAIN = BACKEND / "main.py"
src = MAIN.read_text(encoding="utf-8")
orig = src

# 4a. Import
if "import memory" not in src:
    anchor = "import chat_store\n"
    if anchor in src:
        src = src.replace(anchor, anchor + "import memory\n", 1)
        note("main.py: import memory")

# 4b. Remember after each turn — insert right before _session_put pair
old_tail = (
    '        history.append({"role": "user", "content": msg})\n'
    '        history.append({"role": "assistant", "content": reply})\n'
    '        _session_put(sid, history[-HISTORY_MAX:])\n'
)
new_tail = (
    '        history.append({"role": "user", "content": msg})\n'
    '        history.append({"role": "assistant", "content": reply})\n'
    '        _session_put(sid, history[-HISTORY_MAX:])\n'
    '\n'
    '        # Semantic memory: store this turn in the background\n'
    '        try:\n'
    '            await asyncio.to_thread(memory.remember, sid, "user", msg)\n'
    '            if reply and 10 < len(reply) < 600:\n'
    '                await asyncio.to_thread(\n'
    '                    memory.remember, sid, "assistant", reply\n'
    '                )\n'
    '        except Exception:\n'
    '            pass\n'
)
if old_tail in src:
    src = src.replace(old_tail, new_tail, 1)
    note("main.py: remember called after WS turn")
elif "memory.remember, sid, \"user\"" in src:
    note("main.py: remember already wired", "skip")
else:
    note("main.py: WS turn tail anchor not found", "warn")

# 4c. Endpoints
if "/memory/status" not in src:
    anchor = '@app.get("/tools")'
    if anchor in src:
        block = '''@app.get("/memory/status")
async def memory_status():
    return memory.status()


@app.post("/memory/clear")
async def memory_clear():
    return {"removed": memory.clear()}


class MemoryRememberRequest(BaseModel):
    chat_id: str = "manual"
    role: str = "user"
    text: str


@app.post("/memory/remember")
async def memory_remember(req: MemoryRememberRequest):
    ok = memory.remember(req.chat_id, req.role, req.text)
    return {"ok": ok}


'''
        src = src.replace(anchor, block + anchor, 1)
        note("main.py: /memory endpoints")

if src != orig:
    MAIN.write_text(src, encoding="utf-8")


# =====================================================================
# 5. .env.example and .env
# =====================================================================
for name in (".env.example", ".env"):
    p = BACKEND / name
    if not p.exists():
        continue
    txt = p.read_text(encoding="utf-8")
    if "MEMORY_ENABLED" not in txt:
        block = (
            "\n# ---------- Semantic memory ----------\n"
            "# Recall relevant past turns and inject them into the prompt.\n"
            "# Requires:  ollama pull nomic-embed-text\n"
            "MEMORY_ENABLED=1\n"
            "MEMORY_MODEL=nomic-embed-text\n"
            "MEMORY_TOP_K=5\n"
            "MEMORY_MIN_SIM=0.45\n"
        )
        txt = txt.rstrip() + block
        p.write_text(txt, encoding="utf-8")
        note(f"backend/{name}: memory vars")


# =====================================================================
# 6. Verify
# =====================================================================
print()
print("=" * 60)
print("Verification")
print("=" * 60)

r = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0,'backend'); "
     "import memory, agent, main, chat_store, config; "
     "print('memory module:', hasattr(memory, 'remember') and hasattr(memory, 'recall')); "
     "print('memory.status():', memory.status()); "
     "print('agent has memory inject:', 'format_for_prompt' in open('backend/agent.py',encoding='utf-8').read()); "
     "print('main has /memory/status:', '/memory/status' in open('backend/main.py',encoding='utf-8').read())"],
    cwd=str(ROOT), capture_output=True, text=True,
)
for line in (r.stdout or "").strip().splitlines():
    print(f"  {line}")
if r.returncode != 0:
    print("  [FAIL]")
    for line in (r.stderr or "").strip().splitlines()[-8:]:
        print("  " + line)

# Recall smoke test
print()
print("Smoke test (recall against empty DB):")
r = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0,'backend'); "
     "import memory; "
     "print('recall empty:', memory.recall('anything', k=3)); "
     "print('format empty:', repr(memory.format_for_prompt('anything', session_id='x')))"],
    cwd=str(ROOT), capture_output=True, text=True,
)
for line in (r.stdout or "").strip().splitlines():
    print(f"  {line}")

print()
print("=" * 60)
print(f"Summary: {sum(1 for _, k in _log if k == 'ok')} applied, "
      f"{sum(1 for _, k in _log if k == 'skip')} skipped, "
      f"{sum(1 for _, k in _log if k == 'warn')} warnings")
print("=" * 60)
for m, k in _log:
    if k == "warn":
        print(f"  [WARN] {m}")
print()
print("Next:")
print("  1. Pull the embedding model:")
print("       ollama pull nomic-embed-text")
print("  2. Restart: python backend\\run.py")
print("  3. Ctrl+Shift+R in the browser")
print("  4. Check status:")
print("       curl http://localhost:8000/memory/status")
print("  5. Ask a few questions. After ~3 turns, memory should start")
print("     storing. Ask something related to a past turn to see it")
print("     in the prompt (set QUILL_AUDIO_DEBUG=1 or check audit log).")
print("=" * 60)