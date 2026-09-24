import os
import base64
import secrets
import json
from hashlib import scrypt
from pathlib import Path
from typing import Optional

import keyring
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


VAULT_PATH = Path(__file__).parent / "vault.enc"
KEYRING_SERVICE = "onyx-local"
KEYRING_USER = "master-key"

SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_LEN = 32


class VaultLockedError(PermissionError):
    pass


class Vault:
    def __init__(self):
        self._master_key: Optional[bytes] = None
        self._data: dict = {}
        self._session_key: Optional[bytes] = None
        self._load_error: Optional[str] = None
        try:
            self._master_key = self._load_or_create_master_key()
            self._data = self._load_vault()
        except Exception as e:
            self._load_error = f"vault unavailable: {e}"

    def _check(self):
        if self._load_error:
            raise RuntimeError(self._load_error)

    def _load_or_create_master_key(self) -> bytes:
        try:
            existing = keyring.get_password(KEYRING_SERVICE, KEYRING_USER)
        except Exception as e:
            raise RuntimeError(f"keyring unavailable: {e}") from e
        if existing:
            return base64.b64decode(existing)
        new_key = secrets.token_bytes(32)
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, base64.b64encode(new_key).decode())
        return new_key

    def _load_vault(self) -> dict:
        if not VAULT_PATH.exists():
            return {}
        raw = VAULT_PATH.read_bytes()
        if len(raw) < 13:
            raise RuntimeError("vault.enc is corrupted (too short)")
        nonce, ct = raw[:12], raw[12:]
        try:
            plaintext = AESGCM(self._master_key).decrypt(nonce, ct, None)
        except Exception as e:
            raise RuntimeError(f"vault.enc failed to decrypt: {e}") from e
        return json.loads(plaintext.decode("utf-8"))

    def _save_vault(self):
        self._check()
        plaintext = json.dumps(self._data).encode("utf-8")
        nonce = secrets.token_bytes(12)
        ct = AESGCM(self._master_key).encrypt(nonce, plaintext, None)
        tmp = VAULT_PATH.with_suffix(".enc.tmp")
        tmp.write_bytes(nonce + ct)
        tmp.replace(VAULT_PATH)

    def _has_passphrase_internal(self) -> bool:
        return "__meta__" in self._data

    def _effective_key(self) -> bytes:
        """
        Return the key used for sensitive entries.

        - If a passphrase is set AND the vault is unlocked -> session key (from passphrase).
        - If no passphrase is set -> master key (from OS keyring).
        - If a passphrase is set but locked -> raises VaultLockedError.
        """
        if self._session_key is not None:
            return self._session_key
        if self._has_passphrase_internal():
            raise VaultLockedError("unlock the vault before accessing sensitive credentials")
        if self._master_key is None:
            raise RuntimeError("vault master key unavailable")
        return self._master_key

    def is_locked(self) -> bool:
        if self._load_error:
            return True
        if not self._has_passphrase_internal():
            return False
        return self._session_key is None

    def has_passphrase(self) -> bool:
        self._check()
        return self._has_passphrase_internal()

    def set_passphrase(self, passphrase: str) -> None:
        self._check()
        if not passphrase or len(passphrase) < 8:
            raise ValueError("passphrase must be at least 8 characters")
        salt = secrets.token_bytes(16)
        key = scrypt(passphrase.encode(), salt=salt, n=SCRYPT_N,
                     r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_LEN)
        self._data["__meta__"] = {
            "salt": base64.b64encode(salt).decode(),
            "verify": base64.b64encode(key).decode(),
        }
        self._session_key = key
        self._save_vault()

    def unlock(self, passphrase: str) -> bool:
        self._check()
        meta = self._data.get("__meta__")
        if not meta:
            return False
        salt = base64.b64decode(meta["salt"])
        key = scrypt(passphrase.encode(), salt=salt, n=SCRYPT_N,
                     r=SCRYPT_R, p=SCRYPT_P, dklen=SCRYPT_LEN)
        if base64.b64encode(key).decode() == meta["verify"]:
            self._session_key = key
            return True
        return False

    def lock(self) -> None:
        self._session_key = None

    def set(self, key: str, value: str, sensitive: bool = False) -> None:
        self._check()
        if sensitive:
            enc_key = self._effective_key()
            nonce = secrets.token_bytes(12)
            blob = AESGCM(enc_key).encrypt(nonce, value.encode(), None)
            self._data[key] = {
                "sensitive": True,
                "blob": base64.b64encode(nonce + blob).decode(),
            }
        else:
            self._data[key] = {"sensitive": False, "value": value}
        self._save_vault()

    def get(self, key: str) -> str:
        self._check()
        entry = self._data.get(key)
        if entry is None or key.startswith("__"):
            return ""
        if not isinstance(entry, dict):
            return str(entry)
        if entry.get("sensitive"):
            enc_key = self._effective_key()
            raw = base64.b64decode(entry["blob"])
            nonce, ct = raw[:12], raw[12:]
            return AESGCM(enc_key).decrypt(nonce, ct, None).decode()
        return entry.get("value", "")

    def get_safe(self, key: str) -> str:
        try:
            return self.get(key)
        except (VaultLockedError, RuntimeError):
            return ""

    def delete(self, key: str) -> None:
        self._check()
        if key in self._data:
            del self._data[key]
            self._save_vault()

    def has(self, key: str) -> bool:
        self._check()
        return key in self._data and not key.startswith("__")

    def keys(self) -> list:
        self._check()
        return [k for k in self._data.keys() if not k.startswith("__")]

    def info(self, key: str) -> dict:
        self._check()
        entry = self._data.get(key)
        if entry is None:
            return {"key": key, "sensitive": False, "exists": False}
        if not isinstance(entry, dict):
            return {"key": key, "sensitive": False, "exists": True}
        return {
            "key": key,
            "sensitive": entry.get("sensitive", False),
            "exists": True,
        }


vault = Vault()


def _cli():
    import sys
    if len(sys.argv) < 2:
        print("usage: vault.py [list|status|set-passphrase|unlock|lock|set|get|delete|has|info]")
        return

    cmd = sys.argv[1]

    if cmd == "list":
        try:
            for k in vault.keys():
                tag = " [sensitive]" if vault.info(k)["sensitive"] else ""
                print(f"  {k}{tag}")
        except RuntimeError as e:
            print(f"vault error: {e}")
        return

    if cmd == "status":
        try:
            print("passphrase set:", vault.has_passphrase())
            print("session:", "locked" if vault.is_locked() else "unlocked")
        except RuntimeError as e:
            print("vault error:", e)
        return

    if cmd == "set-passphrase":
        if len(sys.argv) < 3:
            print("usage: vault.py set-passphrase <passphrase>")
            return
        vault.set_passphrase(sys.argv[2])
        print("passphrase set; vault unlocked")
        return

    if cmd == "unlock":
        if len(sys.argv) < 3:
            print("usage: vault.py unlock <passphrase>")
            return
        print("unlocked" if vault.unlock(sys.argv[2]) else "wrong passphrase")
        return

    if cmd == "lock":
        vault.lock()
        print("vault locked")
        return

    if cmd == "set":
        if len(sys.argv) < 4:
            print("usage: vault.py set <key> <value> [--sensitive]")
            return
        sensitive = "--sensitive" in sys.argv
        vault.set(sys.argv[2], sys.argv[3], sensitive=sensitive)
        print(f"stored '{sys.argv[2]}'" + (" (sensitive)" if sensitive else ""))
        return

    if cmd == "get":
        if len(sys.argv) < 3:
            return
        try:
            print(vault.get(sys.argv[2]) or f"'{sys.argv[2]}' not found")
        except VaultLockedError:
            print(f"'{sys.argv[2]}' is locked. run: vault.py unlock <passphrase>")
        except RuntimeError as e:
            print(f"vault error: {e}")
        return

    if cmd == "delete":
        if len(sys.argv) < 3:
            return
        vault.delete(sys.argv[2])
        print(f"deleted '{sys.argv[2]}'")
        return

    if cmd == "has":
        if len(sys.argv) < 3:
            return
        print("yes" if vault.has(sys.argv[2]) else "no")
        return

    if cmd == "info":
        if len(sys.argv) < 3:
            return
        print(json.dumps(vault.info(sys.argv[2]), indent=2))
        return

    print(f"unknown command: {cmd}")


if __name__ == "__main__":
    _cli()