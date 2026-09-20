"""Onyx credential vault — AES-256-GCM encrypted storage.

Master key lives in the OS keychain (Windows Credential Manager, macOS
Keychain, Linux Secret Service). The vault file on disk is pure ciphertext.

Usage from CLI:
    python vault.py set GITHUB_PERSONAL_ACCESS_TOKEN ghp_xxx
    python vault.py get GITHUB_PERSONAL_ACCESS_TOKEN
    python vault.py list
    python vault.py delete GITHUB_PERSONAL_ACCESS_TOKEN

Usage from code:
    from vault import vault
    token = vault.get("GITHUB_PERSONAL_ACCESS_TOKEN")
"""

import sys
import json
import secrets
from base64 import b64encode, b64decode
from pathlib import Path

import keyring
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


VAULT_PATH = Path(__file__).parent / "vault.enc"
KEYRING_SERVICE = "onyx-local"
KEYRING_USER = "master-key"


class Vault:
    def __init__(self):
        self._key = self._load_or_create_key()
        self._data = self._load_vault()

    def _load_or_create_key(self) -> bytes:
        """Fetch the master key from the OS keychain, or generate one."""
        try:
            existing = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception as e:
            raise RuntimeError(f"Keyring unavailable: {e}") from e

        if existing:
            return b64decode(existing)

        new_key = secrets.token_bytes(32)  # 256-bit
        keyring.set_password(
            KEYRING_SERVICE, KEYRING_USER, b64encode(new_key).decode()
        )
        print("[Vault] Generated new master key in OS keychain")
        return new_key

    def _load_vault(self) -> dict:
        if not VAULT_PATH.exists():
            return {}
        try:
            raw = VAULT_PATH.read_bytes()
            if len(raw) < 13:
                return {}
            nonce, ct = raw[:12], raw[12:]
            plaintext = AESGCM(self._key).decrypt(nonce, ct, None)
            return json.loads(plaintext.decode("utf-8"))
        except Exception as e:
            print(f"[Vault] Could not decrypt vault: {e}")
            return {}

    def _save_vault(self):
        plaintext = json.dumps(self._data).encode("utf-8")
        nonce = secrets.token_bytes(12)
        ct = AESGCM(self._key).encrypt(nonce, plaintext, None)
        VAULT_PATH.write_bytes(nonce + ct)

    def get(self, key: str) -> str:
        return self._data.get(key, "")

    def set(self, key: str, value: str):
        self._data[key] = value
        self._save_vault()

    def delete(self, key: str):
        if key in self._data:
            del self._data[key]
            self._save_vault()

    def has(self, key: str) -> bool:
        return key in self._data

    def keys(self) -> list:
        return list(self._data.keys())


# Singleton
vault = Vault()


# ---------- CLI ----------
def _cli():
    if len(sys.argv) < 2:
        print("Usage: python vault.py [set|get|list|delete|has] [key] [value]")
        return

    cmd = sys.argv[1]

    if cmd == "list":
        keys = vault.keys()
        if not keys:
            print("Vault is empty.")
        else:
            for k in keys:
                print(f"  {k}")
        return

    if cmd == "set":
        if len(sys.argv) < 4:
            print("Usage: python vault.py set <key> <value>")
            return
        vault.set(sys.argv[2], sys.argv[3])
        print(f"Stored '{sys.argv[2]}' in vault.")
        return

    if cmd == "get":
        if len(sys.argv) < 3:
            print("Usage: python vault.py get <key>")
            return
        val = vault.get(sys.argv[2])
        if not val:
            print(f"'{sys.argv[2]}' not in vault.")
        else:
            print(val)
        return

    if cmd == "delete":
        if len(sys.argv) < 3:
            print("Usage: python vault.py delete <key>")
            return
        vault.delete(sys.argv[2])
        print(f"Removed '{sys.argv[2]}' from vault.")
        return

    if cmd == "has":
        if len(sys.argv) < 3:
            print("Usage: python vault.py has <key>")
            return
        print("yes" if vault.has(sys.argv[2]) else "no")
        return

    print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    _cli()