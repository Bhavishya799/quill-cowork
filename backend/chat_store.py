"""Chat history persistence via SQLite.

Append-only: messages are upserted by (chat_id, msg_id), never deleted
by a save. Deletion is explicit via delete_chat/delete_message.
Text fields are encrypted at rest via chat_crypto.
"""
from __future__ import annotations
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional

import chat_crypto

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
        try:
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_messages_unique "
                      "ON messages(chat_id, msg_id)")
            has_unique = True
        except sqlite3.IntegrityError:
            has_unique = False
            print("[chat_store] warning: duplicate (chat_id,msg_id) rows; "
                  "unique index not created")
        # Migration: encrypt any plaintext rows
        try:
            chat_crypto.migrate_table(c, "messages", ["text"])
        except Exception:
            pass


def _has_unique_index(c) -> bool:
    row = c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_messages_unique'"
    ).fetchone()
    return bool(row)


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
        {"id": r[0], "title": r[1], "created_at": r[2],
         "updated_at": r[3], "message_count": r[4]}
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
            {"id": m[0], "role": m[1],
             "text": chat_crypto.decrypt(m[2] or ""),
             **_safe_json(m[3])}
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
        has_unique = _has_unique_index(c)
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
            meta = {k: v for k, v in m.items() if k not in ("id", "role", "text")}
            meta_json = json.dumps(meta, default=str) if meta else None
            enc = chat_crypto.encrypt(text)
            if has_unique:
                c.execute(
                    "INSERT INTO messages(chat_id, msg_id, role, text, meta_json, ts) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(chat_id, msg_id) DO UPDATE SET "
                    "  role = excluded.role, text = excluded.text, "
                    "  meta_json = excluded.meta_json",
                    (chat_id, mid, role, enc, meta_json, now + i * 0.001),
                )
            else:
                exists = c.execute(
                    "SELECT 1 FROM messages WHERE chat_id = ? AND msg_id = ?",
                    (chat_id, mid),
                ).fetchone()
                if exists:
                    c.execute(
                        "UPDATE messages SET role = ?, text = ?, meta_json = ? "
                        "WHERE chat_id = ? AND msg_id = ?",
                        (role, enc, meta_json, chat_id, mid),
                    )
                else:
                    c.execute(
                        "INSERT INTO messages(chat_id, msg_id, role, text, meta_json, ts) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (chat_id, mid, role, enc, meta_json, now + i * 0.001),
                    )


def append_message(chat_id: str, msg_id: int, role: str, text: str,
                   meta: Optional[Dict] = None) -> None:
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO messages(chat_id, msg_id, role, text, meta_json, ts) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (chat_id, msg_id, role, chat_crypto.encrypt(text or ""),
             json.dumps(meta or {}, default=str) if meta else None, time.time()),
        )
        c.execute("UPDATE chats SET updated_at = ? WHERE id = ?",
                  (time.time(), chat_id))


def delete_message(chat_id: str, msg_id: int) -> bool:
    with _lock, _conn() as c:
        cur = c.execute(
            "DELETE FROM messages WHERE chat_id = ? AND msg_id = ?",
            (chat_id, msg_id),
        )
        return cur.rowcount > 0


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
