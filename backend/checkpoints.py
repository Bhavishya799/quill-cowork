"""Workspace checkpoints + rewind for destructive file ops.

Before any write/patch/append, snapshot the target file to
workspace/.quill/checkpoints/<ts>/<hash>_<basename>. Record in
chat.db checkpoints table. rewind(id) restores the file (or deletes
it if it did not exist before the write).
"""
from __future__ import annotations
import hashlib
import json
import shutil
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

from config import settings

DB_PATH = Path(__file__).parent / "workspace" / ".quill" / "chat.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
CKPT_ROOT = Path(settings.WORKSPACE_ROOT) / ".quill" / "checkpoints"
CKPT_ROOT.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  chat_id TEXT NOT NULL,
  tool TEXT NOT NULL,
  args_json TEXT NOT NULL,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checkpoints_chat ON checkpoints(chat_id, created_at DESC);
CREATE TABLE IF NOT EXISTS checkpoint_files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  checkpoint_id INTEGER NOT NULL,
  original_path TEXT NOT NULL,
  backup_path TEXT,
  existed INTEGER NOT NULL,
  FOREIGN KEY(checkpoint_id) REFERENCES checkpoints(id)
);
"""

def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(DB_PATH), timeout=10)
    c.execute("PRAGMA journal_mode = WAL")
    return c

def init() -> None:
    with _lock, _conn() as c:
        c.executescript(_SCHEMA)

def _record(chat_id: str, tool: str, args: dict) -> int:
    init()
    with _lock, _conn() as c:
        cur = c.execute(
            "INSERT INTO checkpoints(chat_id, tool, args_json, created_at) VALUES (?, ?, ?, ?)",
            (chat_id, tool, json.dumps(args, default=str), time.time()),
        )
        return cur.lastrowid

def _targets_for(tool: str, args: dict):
    targets = []
    if tool == "write_file":
        try:
            from tools.filesystem import _resolve
            p = _resolve(args.get("path", ""), write=True)
            targets.append((p, "file"))
        except Exception:
            pass
    elif tool in ("codebase_write", "codebase_patch"):
        try:
            import codebase as cb
            meta = cb.get_meta(args.get("name", ""))
            if meta:
                p = (Path(meta["root"]) / args.get("path", "")).resolve()
                if p.is_relative_to(Path(meta["root"])):
                    targets.append((p, "file"))
        except Exception:
            pass
    elif tool in ("obsidian_write_note", "obsidian_append_note"):
        try:
            from tools.obsidian import _safe_note
            p = _safe_note(args.get("name", ""))
            targets.append((p, "file"))
        except Exception:
            pass
    return targets

def snapshot(chat_id: str, tool: str, args: dict) -> Optional[int]:
    targets = _targets_for(tool, args)
    if not targets:
        return None
    try:
        cid = _record(chat_id, tool, args)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        base = CKPT_ROOT / stamp
        base.mkdir(parents=True, exist_ok=True)
        with _lock, _conn() as c:
            for path, kind in targets:
                existed = path.is_file()
                backup = None
                if existed:
                    h = hashlib.sha256(str(path).encode()).hexdigest()[:10]
                    backup = base / f"{h}_{path.name}"
                    shutil.copy2(path, backup)
                c.execute(
                    "INSERT INTO checkpoint_files(checkpoint_id, original_path, backup_path, existed) "
                    "VALUES (?, ?, ?, ?)",
                    (cid, str(path), str(backup) if backup else None, 1 if existed else 0),
                )
        return cid
    except Exception:
        return None

def list_for_chat(chat_id: str, limit: int = 50) -> list:
    init()
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, tool, args_json, created_at FROM checkpoints "
            "WHERE chat_id = ? ORDER BY created_at DESC LIMIT ?",
            (chat_id, limit),
        ).fetchall()
    return [
        {"id": r[0], "tool": r[1], "args": json.loads(r[2]), "created_at": r[3]}
        for r in rows
    ]

def rewind(checkpoint_id: int) -> dict:
    init()
    restored, deleted, errors = 0, 0, []
    with _lock, _conn() as c:
        files = c.execute(
            "SELECT original_path, backup_path, existed FROM checkpoint_files "
            "WHERE checkpoint_id = ?", (checkpoint_id,),
        ).fetchall()
        for path_str, backup, existed in files:
            try:
                path = Path(path_str)
                if existed and backup and Path(backup).is_file():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(backup, path)
                    restored += 1
                elif not existed and path.is_file():
                    path.unlink()
                    deleted += 1
            except Exception as e:
                errors.append(f"{path_str}: {e}")
    return {"ok": not errors, "restored": restored, "deleted": deleted, "errors": errors}
