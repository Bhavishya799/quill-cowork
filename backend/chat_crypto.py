"""Application-layer AES-GCM encryption for chat.db text fields.

Encrypts message text and memory text using the vault's effective key.
Legacy plaintext passes through unchanged; migration re-encrypts lazily
on init or eagerly on next write. Sentinel "QENCv1:" marks ciphertext.
"""
from __future__ import annotations
import base64
import secrets
from typing import Optional

from vault import vault
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

PREFIX = "QENCv1:"

def _key() -> Optional[bytes]:
    try:
        return vault._effective_key()
    except Exception:
        return None

def encrypt(text: str) -> str:
    if not text or text.startswith(PREFIX):
        return text
    key = _key()
    if key is None:
        return text
    nonce = secrets.token_bytes(12)
    ct = AESGCM(key).encrypt(nonce, text.encode("utf-8"), None)
    return PREFIX + base64.b64encode(nonce + ct).decode("ascii")

def decrypt(value: str) -> str:
    if not value or not value.startswith(PREFIX):
        return value
    key = _key()
    if key is None:
        return "[encrypted — unlock vault]"
    try:
        raw = base64.b64decode(value[len(PREFIX):])
        nonce, ct = raw[:12], raw[12:]
        return AESGCM(key).decrypt(nonce, ct, None).decode("utf-8")
    except Exception:
        return "[decrypt failed]"

def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(PREFIX)

def migrate_table(conn, table: str, text_cols: list) -> int:
    if _key() is None:
        return 0
    cols = ", ".join(text_cols)
    rows = conn.execute(f"SELECT rowid, {cols} FROM {table}").fetchall()
    changed = 0
    for row in rows:
        rowid = row[0]
        updates = {}
        for i, col in enumerate(text_cols, start=1):
            val = row[i]
            if val and not is_encrypted(val):
                updates[col] = encrypt(val)
        if updates:
            set_clause = ", ".join(f"{c} = ?" for c in updates)
            conn.execute(
                f"UPDATE {table} SET {set_clause} WHERE rowid = ?",
                (*updates.values(), rowid),
            )
            changed += 1
    if changed:
        conn.commit()
    return changed
