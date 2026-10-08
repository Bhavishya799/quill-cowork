"""Chat history persistence via SQLite.

Single-user local-first: one DB file at backend/workspace/.quill/chat.db.
All writes serialized through a lock. WAL journal for concurrent reads.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

DB_PATH = Path(__file__).parent / "workspace" / ".quill" / "chat.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT 'New task',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id TEXT NOT NULL,
  msg_id INTEGER NOT NULL,
  role TEXT NOT NULL,
  text TEXT,
  meta_json TEXT,
  ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_chat_ts ON messages(chat_id, ts);
CREATE INDEX IF NOT EXISTS idx_messages_chat_mid ON messages(chat_id, msg_id);
"""


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=10)
    c.execute("PRAGMA journal_mode = WAL")
    return c


def init() -> None:
    with _lock, _conn() as c:
        c.executescript(_SCHEMA)


def _safe_json(s: Optional[str]) -> dict:
    if not s:
        return {}
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else {}
    except Exception:
        return {}


def list_chats() -> List[Dict]:
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT c.id, c.title, c.created_at, c.updated_at, "
            "(SELECT COUNT(*) FROM messages WHERE chat_id = c.id) "
            "FROM chats c ORDER BY c.updated_at DESC"
        ).fetchall()
    return [
        {
            "id": r[0], "title": r[1],
            "created_at": r[2], "updated_at": r[3],
            "message_count": r[4],
        }
        for r in rows
    ]


def get_chat(chat_id: str) -> Optional[Dict]:
    with _lock, _conn() as c:
        row = c.execute(
            "SELECT id, title, created_at, updated_at FROM chats WHERE id = ?",
            (chat_id,),
        ).fetchone()
        if not row:
            return None
        msgs = c.execute(
            "SELECT msg_id, role, text, meta_json FROM messages "
            "WHERE chat_id = ? ORDER BY ts, id",
            (chat_id,),
        ).fetchall()
    return {
        "id": row[0], "title": row[1],
        "created_at": row[2], "updated_at": row[3],
        "messages": [
            {"id": m[0], "role": m[1], "text": m[2] or "", **_safe_json(m[3])}
            for m in msgs
        ],
    }


def upsert_chat(chat_id: str, title: str, messages: List[Dict]) -> None:
    now = time.time()
    with _lock, _conn() as c:
        existing = c.execute(
            "SELECT created_at FROM chats WHERE id = ?", (chat_id,)
        ).fetchone()
        created = existing[0] if existing else now
        c.execute(
            "INSERT INTO chats(id, title, created_at, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "  title = excluded.title, updated_at = excluded.updated_at",
            (chat_id, title or "New task", created, now),
        )
        c.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        for i, m in enumerate(messages or []):
            if not isinstance(m, dict):
                continue
            mid = m.get("id")
            if not isinstance(mid, int):
                mid = i
            role = m.get("role") or "assistant"
            text = m.get("text")
            if not isinstance(text, str):
                text = "" if text is None else str(text)
            meta = {k: v for k, v in m.items()
                    if k not in ("id", "role", "text")}
            c.execute(
                "INSERT INTO messages(chat_id, msg_id, role, text, "
                "meta_json, ts) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    chat_id, mid, role, text,
                    json.dumps(meta, default=str) if meta else None,
                    now + i * 0.001,
                ),
            )


def rename_chat(chat_id: str, title: str) -> bool:
    with _lock, _conn() as c:
        cur = c.execute(
            "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?",
            (title or "New task", time.time(), chat_id),
        )
        return cur.rowcount > 0


def delete_chat(chat_id: str) -> bool:
    with _lock, _conn() as c:
        c.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
        cur = c.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
        return cur.rowcount > 0
