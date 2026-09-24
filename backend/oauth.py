"""Minimal Google OAuth 2.0 helper. No external SDK, just httpx + vault."""
import os
import time
import secrets
from typing import Optional, Tuple
from urllib.parse import urlencode

import httpx

from vault import vault

GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"

GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

VAULT_KEYS = {
    "refresh": "GOOGLE_REFRESH_TOKEN",
    "access": "GOOGLE_ACCESS_TOKEN",
    "expires": "GOOGLE_TOKEN_EXPIRES",
    "state": "GOOGLE_OAUTH_STATE",
}


def _env(name: str) -> str:
    return os.getenv(name, "").strip()


def _client_id() -> str:
    return vault.get_safe("GOOGLE_CLIENT_ID") or _env("GOOGLE_CLIENT_ID")


def _client_secret() -> str:
    return vault.get_safe("GOOGLE_CLIENT_SECRET") or _env("GOOGLE_CLIENT_SECRET")


def _redirect_uri() -> str:
    return _env("GOOGLE_REDIRECT_URI") or "http://localhost:8000/oauth/google/callback"


def is_configured() -> bool:
    return bool(_client_id() and _client_secret())


def is_connected() -> bool:
    return bool(vault.get_safe(VAULT_KEYS["refresh"]))


def google_auth_url() -> str:
    state = secrets.token_urlsafe(24)
    try:
        vault.set(VAULT_KEYS["state"], state)
    except Exception:
        pass
    params = {
        "client_id": _client_id(),
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": " ".join(GMAIL_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH}?{urlencode(params)}"


def exchange_code(code: str, state: Optional[str] = None) -> Tuple[bool, str]:
    expected = vault.get_safe(VAULT_KEYS["state"])
    if expected and state and state != expected:
        return False, "state mismatch"
    try:
        r = httpx.post(
            GOOGLE_TOKEN,
            data={
                "code": code,
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "redirect_uri": _redirect_uri(),
                "grant_type": "authorization_code",
            },
            timeout=20,
        )
    except Exception as e:
        return False, f"token exchange failed: {e}"
    if r.status_code != 200:
        return False, f"token exchange HTTP {r.status_code}: {r.text[:200]}"
    _store(r.json())
    return True, "connected"


def access_token() -> str:
    refresh = vault.get_safe(VAULT_KEYS["refresh"])
    if not refresh:
        return ""
    try:
        expires = float(vault.get_safe(VAULT_KEYS["expires"]) or "0")
    except ValueError:
        expires = 0.0
    if time.time() < expires - 30:
        tok = vault.get_safe(VAULT_KEYS["access"])
        if tok:
            return tok
    return _refresh(refresh)


def _refresh(refresh_token: str) -> str:
    try:
        r = httpx.post(
            GOOGLE_TOKEN,
            data={
                "client_id": _client_id(),
                "client_secret": _client_secret(),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
    except Exception:
        return ""
    if r.status_code != 200:
        return ""
    _store(r.json(), keep_refresh=refresh_token)
    return vault.get_safe(VAULT_KEYS["access"])


def _store(payload: dict, keep_refresh: Optional[str] = None) -> None:
    access = payload.get("access_token", "")
    refresh = payload.get("refresh_token") or keep_refresh or ""
    expires_in = int(payload.get("expires_in", 3600))
    if access:
        vault.set(VAULT_KEYS["access"], access, sensitive=True)
    if refresh:
        vault.set(VAULT_KEYS["refresh"], refresh, sensitive=True)
    vault.set(VAULT_KEYS["expires"], str(time.time() + expires_in))


def disconnect() -> None:
    for k in VAULT_KEYS.values():
        try:
            vault.delete(k)
        except Exception:
            pass


def status() -> dict:
    return {
        "configured": is_configured(),
        "connected": is_connected(),
        "redirect_uri": _redirect_uri(),
    }