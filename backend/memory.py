"""Semantic memory over chat history.

Vector-indexed recall (numpy matrix cache) + AES-GCM text at rest.
Same DB as chat history. Text columns encrypted via chat_crypto.

Env:
  MEMORY_ENABLED   1 | 0    (default 1)
  MEMORY_MODEL     Ollama embedding model (default nomic-embed-text)
  MEMORY_TOP_K     memories to inject per turn (default 5)
  MEMORY_MIN_SIM   cosine threshold (default 0.45)
"""
from __future__ import annotations
import hashlib
import os
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

import chat_crypto

DB_PATH = Path(__file__).parent / "workspace" / ".quill" / "chat.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_embed_lock = threading.Lock()
_embed_err: Optional[str] = None

_cache = {"ids": [], "chat_ids": [], "matrix": None, "norms": None,
          "ts": 0.0, "version": 0}
_CACHE_TTL = 60.0


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


_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id TEXT,
  role TEXT NOT NULL,
  text TEXT NOT NULL,
  text_hash TEXT,
  embedding BLOB NOT NULL,
  dim INTEGER NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_created ON memories(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memories_chat ON memories(chat_id);
CREATE INDEX IF NOT EXISTS idx_memories_hash ON memories(text_hash);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=10)
    c.execute("PRAGMA journal_mode = WAL")
    return c


def init() -> None:
    with _lock, _conn() as c:
        c.executescript(_SCHEMA)
        cols = [row[1] for row in c.execute("PRAGMA table_info(memories)").fetchall()]
        if "text_hash" not in cols:
            c.execute("ALTER TABLE memories ADD COLUMN text_hash TEXT")
            c.execute("CREATE INDEX IF NOT EXISTS idx_memories_hash ON memories(text_hash)")
        try:
            chat_crypto.migrate_table(c, "memories", ["text"])
        except Exception:
            pass
        # Backfill text_hash for legacy rows
        rows = c.execute("SELECT id, text FROM memories WHERE text_hash IS NULL").fetchall()
        for rid, val in rows:
            plain = chat_crypto.decrypt(val) if chat_crypto.is_encrypted(val) else val
            if plain and not plain.startswith("["):
                c.execute("UPDATE memories SET text_hash = ? WHERE id = ?",
                          (hashlib.sha256(plain.encode("utf-8")).hexdigest(), rid))
        c.commit()


def _embed_sync(text: str) -> Optional[List[float]]:
    global _embed_err
    if not text:
        return None
    with _embed_lock:
        try:
            import ollama
            client = ollama.Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"))
            model = _model_name()
            if hasattr(client, "embed"):
                try:
                    r = client.embed(model=model, input=text)
                    vecs = r.get("embeddings") if isinstance(r, dict) else getattr(r, "embeddings", None)
                    if vecs:
                        _embed_err = None
                        return list(vecs[0])
                except Exception:
                    pass
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


_GREETINGS = {"hi", "hello", "hey", "thanks", "thank you",
              "good morning", "good night", "bye", "ok", "okay"}


def _is_noise(text: str, role: str) -> bool:
    t = text.strip().lower()
    if len(t) < 10:
        return True
    if t in _GREETINGS:
        return True
    if role == "assistant" and len(text) > 600:
        return True
    return False


def remember(chat_id: str, role: str, text: str) -> bool:
    global _cache
    if not is_enabled():
        return False
    text = (text or "").strip()
    if not text or _is_noise(text, role):
        return False
    if len(text) > 2000:
        text = text[:2000]
    init()
    text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    with _lock:
        conn = _conn()
        try:
            row = conn.execute("SELECT 1 FROM memories WHERE text_hash = ? LIMIT 1",
                               (text_hash,)).fetchone()
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
                "INSERT INTO memories (chat_id, role, text, text_hash, "
                "embedding, dim, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (chat_id, role, chat_crypto.encrypt(text), text_hash,
                 blob, len(vec), time.time()),
            )
            conn.commit()
        finally:
            conn.close()
    _cache["version"] += 1
    return True


def _load_cache(conn) -> None:
    rows = conn.execute(
        "SELECT id, chat_id, embedding FROM memories ORDER BY id"
    ).fetchall()
    ids = [r[0] for r in rows]
    chat_ids = [r[1] for r in rows]
    if rows:
        matrix = np.vstack([_from_blob(r[2]) for r in rows]).astype(np.float32)
        norms = np.linalg.norm(matrix, axis=1)
    else:
        matrix = np.zeros((0, 0), dtype=np.float32)
        norms = np.array([])
    _cache.update({"ids": ids, "chat_ids": chat_ids,
                   "matrix": matrix, "norms": norms,
                   "ts": time.time(), "version": _cache["version"]})


def recall(query: str, k: int = 5, exclude_chat: Optional[str] = None,
           min_similarity: Optional[float] = None) -> List[Dict]:
    if not is_enabled() or not query:
        return []
    q_vec = embed(query)
    if not q_vec:
        return []
    q = np.asarray(q_vec, dtype=np.float32)
    init()
    with _lock:
        conn = _conn()
        try:
            if (_cache["matrix"] is None
                    or time.time() - _cache["ts"] > _CACHE_TTL
                    or _cache["version"] != _cache["version"]):
                _load_cache(conn)
            matrix = _cache["matrix"]
            if matrix.size == 0:
                return []
            qn = float(np.linalg.norm(q)) or 1e-12
            sims = (matrix @ q) / (_cache["norms"] * qn + 1e-12)
            order = np.argsort(-sims)
            cutoff = min_similarity if min_similarity is not None else _min_sim()
            top_ids, top_sims = [], []
            for idx in order:
                if len(top_ids) >= max(1, k):
                    break
                if float(sims[idx]) < cutoff:
                    break
                if exclude_chat and _cache["chat_ids"][idx] == exclude_chat:
                    continue
                top_ids.append(_cache["ids"][idx])
                top_sims.append(float(sims[idx]))
            if not top_ids:
                return []
            placeholders = ",".join("?" * len(top_ids))
            text_rows = dict(conn.execute(
                f"SELECT id, text FROM memories WHERE id IN ({placeholders})",
                top_ids,
            ).fetchall())
            out = []
            for rid, sim in zip(top_ids, top_sims):
                out.append({
                    "id": rid,
                    "text": chat_crypto.decrypt(text_rows.get(rid, "")),
                    "similarity": round(sim, 3),
                })
            return out
        finally:
            conn.close()


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
    lines = ["Relevant context from past conversations (use only if helpful;",
             "do not explicitly reference this list to the user):"]
    for h in hits:
        txt = (h["text"] or "").replace("\n", " ").strip()[:200]
        lines.append(f'- "{txt}"')
    return "\n".join(lines)


def status() -> dict:
    info = {"enabled": is_enabled(), "model": _model_name(),
            "top_k": _top_k(), "min_similarity": _min_sim(), "error": _embed_err}
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
    global _cache
    with _lock:
        conn = _conn()
        try:
            n = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            conn.execute("DELETE FROM memories")
            conn.commit()
            return int(n)
        finally:
            conn.close()
    _cache = {"ids": [], "chat_ids": [], "matrix": None, "norms": None,
              "ts": 0.0, "version": 0}
