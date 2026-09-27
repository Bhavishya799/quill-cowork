"""Folder grants — user-approved directories the AI can read/write."""
import json
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

from vault import vault


GRANTS_KEY = "QUILL_FOLDER_GRANTS"

HARD_REFUSE = [
    ".ssh", ".aws", ".gnupg", ".kube",
    "AppData/Local/Google/Chrome/User Data",
    "AppData/Local/Microsoft/Edge/User Data",
    "AppData/Roaming/Mozilla/Firefox/Profiles",
    "Windows", "System32",
    "etc/shadow", "etc/passwd",
    "Cookies", "Login Data", "keychain",
    "id_rsa", "id_ed25519", "id_ecdsa",
]

WARN_LIST = [
    ".git", "AppData", ".config", "secrets",
    "credentials", "passwords", "tokens",
    "node_modules", "venv", ".venv",
]


def _load() -> Dict[str, dict]:
    try:
        raw = vault.get_safe(GRANTS_KEY)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save(data: Dict[str, dict]) -> None:
    vault.set(GRANTS_KEY, json.dumps(data))


def _norm(path: str) -> str:
    try:
        return str(Path(path).expanduser().resolve())
    except Exception:
        return str(path)


def list_grants() -> List[dict]:
    return list(_load().values())


def get_grant(path: str) -> Optional[dict]:
    return _load().get(_norm(path))


def add_grant(path: str, label: str = "", read: bool = True, write: bool = True) -> dict:
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ValueError(f"path does not exist: {p}")
    if not p.is_dir():
        raise ValueError(f"not a directory: {p}")
    key = str(p)
    data = _load()
    entry = {
        "path": key,
        "label": label or p.name,
        "read": bool(read),
        "write": bool(write),
        "granted_at": time.time(),
    }
    data[key] = entry
    _save(data)
    return entry


def remove_grant(path: str) -> bool:
    data = _load()
    key = _norm(path)
    if key in data:
        del data[key]
        _save(data)
        return True
    return False


def _path_components(path_str: str) -> set:
    parts = re.split(r"[\\/]+", str(path_str))
    return {p.lower() for p in parts if p}


def _matches(path_str: str, needles: List[str]) -> Optional[str]:
    """Match needle as a whole path component, not a substring.
    Avoids '.ssh' matching '.ssh-backup'."""
    components = _path_components(path_str)
    for needle in needles:
        # Take the last component of the needle (so nested needles still work)
        needle_leaf = needle.replace("\\", "/").split("/")[-1].lower()
        if needle_leaf and needle_leaf in components:
            return needle
    return None


def is_hard_refused(path: str) -> Optional[str]:
    return _matches(path, HARD_REFUSE)


def is_warned(path: str) -> Optional[str]:
    return _matches(path, WARN_LIST)


def resolve_under_grants(target: Path) -> Optional[dict]:
    try:
        target = target.resolve()
    except Exception:
        return None
    for entry in list_grants():
        try:
            base = Path(entry["path"]).resolve()
            if target == base or target.is_relative_to(base):
                return entry
        except Exception:
            continue
    return None