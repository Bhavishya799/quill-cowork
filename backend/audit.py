"""Append-only audit log with hash-chaining (tamper-evident).

Each entry carries prev_hash and hash. hash = sha256(prev_hash + json(entry minus hash)).
verify() walks the whole chain and reports any tampered line.
"""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from safety import redact_log

LOG = Path(__file__).parent / "audit.log.jsonl"
_lock = Lock()
_GENESIS = "0" * 64
_last = {"value": None}

def _load_last_hash() -> str:
    if _last["value"] is not None:
        return _last["value"]
    if not LOG.exists():
        _last["value"] = _GENESIS
        return _GENESIS
    last = _GENESIS
    try:
        with LOG.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    last = json.loads(line).get("hash") or last
                except Exception:
                    continue
    except Exception:
        pass
    _last["value"] = last
    return last

def _compute_hash(prev: str, entry: dict) -> str:
    payload = prev + json.dumps(entry, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def log_event(event_type: str, **fields):
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "type": event_type}
    for k, v in fields.items():
        if isinstance(v, str):
            v = redact_log(v)[:500]
        entry[k] = v
    with _lock:
        prev = _load_last_hash()
        entry["prev_hash"] = prev
        entry["hash"] = _compute_hash(prev, entry)
        line = json.dumps(entry, default=str)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        _last["value"] = entry["hash"]

def recent(limit: int = 100) -> list:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines()[-limit:]:
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out

def stats() -> dict:
    if not LOG.exists():
        return {"total": 0, "by_type": {}}
    counts = {}
    total = 0
    for line in LOG.read_text(encoding="utf-8").splitlines():
        total += 1
        try:
            t = json.loads(line).get("type", "unknown")
            counts[t] = counts.get(t, 0) + 1
        except Exception:
            continue
    return {"total": total, "by_type": counts}

def verify() -> dict:
    if not LOG.exists():
        return {"ok": True, "total": 0, "legacy": 0, "errors": []}
    errors = []
    prev = _GENESIS
    total = 0
    legacy = 0
    for i, line in enumerate(LOG.read_text(encoding="utf-8").splitlines(), 1):
        try:
            entry = json.loads(line)
        except Exception as e:
            errors.append({"line": i, "error": f"parse: {e}"})
            continue
        if "hash" not in entry:
            legacy += 1
            continue
        total += 1
        if entry.get("prev_hash") != prev:
            errors.append({"line": i, "error": "prev_hash mismatch"})
        check = {k: v for k, v in entry.items() if k != "hash"}
        if entry.get("hash") != _compute_hash(entry.get("prev_hash", ""), check):
            errors.append({"line": i, "error": "hash mismatch"})
        prev = entry.get("hash", "")
    return {"ok": not errors, "total": total, "legacy": legacy, "errors": errors[:20]}
