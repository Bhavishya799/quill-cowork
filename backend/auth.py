"""Cookie-based session auth for the local Quill web UI.

Disabled by default. To enable, store a password hash in the vault:

    python -c "import hashlib; print(hashlib.sha256(b'YOUR-PW').hexdigest())"
    python vault.py set QUILL_WEB_PASSWORD <the-hex-hash> --sensitive

When the vault key is absent, every request is allowed (dev mode).
When present, all routes require a valid session cookie.
"""
import hashlib
import hmac
import secrets
import time
from typing import Optional

from fastapi import Request

from vault import vault

PASSWORD_KEY = "QUILL_WEB_PASSWORD"
COOKIE_NAME = "quill_session"
SESSION_TTL = 86400 * 7

_sessions: dict = {}


def is_enabled() -> bool:
    return bool(vault.get_safe(PASSWORD_KEY))


def _stored_hash() -> str:
    return vault.get_safe(PASSWORD_KEY) or ""


def hash_password(password: str) -> str:
    """Generate a salted scrypt hash. Store this in the vault with:
        python vault.py set QUILL_WEB_PASSWORD "<returned-value>" --sensitive
    """
    import base64
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                             n=2**14, r=8, p=1, dklen=32)
    return ("scrypt$"
            + base64.b64encode(salt).decode()
            + "$"
            + base64.b64encode(derived).decode())


def verify_password(password: str) -> bool:
    stored = _stored_hash()
    if not stored or not password:
        return False
    # New format: scrypt$base64(salt)$base64(hash)
    if stored.startswith("scrypt$"):
        try:
            import base64
            _, salt_b64, hash_b64 = stored.split("$", 2)
            salt = base64.b64decode(salt_b64)
            expected = base64.b64decode(hash_b64)
            actual = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                                    n=2**14, r=8, p=1, dklen=32)
            return hmac.compare_digest(actual, expected)
        except Exception:
            return False
    # Legacy format: unsalted SHA-256 (kept for backward compatibility)
    h = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(h, stored)


def issue_token() -> str:
    tok = secrets.token_urlsafe(32)
    _sessions[tok] = time.time() + SESSION_TTL
    return tok


def verify_token(tok: Optional[str]) -> bool:
    if not tok:
        return False
    exp = _sessions.get(tok)
    if exp is None:
        return False
    if time.time() > exp:
        _sessions.pop(tok, None)
        return False
    return True


def revoke_token(tok: Optional[str]) -> None:
    if tok:
        _sessions.pop(tok, None)


def check_request(request: Request) -> bool:
    if not is_enabled():
        return True
    return verify_token(request.cookies.get(COOKIE_NAME))