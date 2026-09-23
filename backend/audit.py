import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

from safety import redact_log


LOG = Path(__file__).parent / "audit.log.jsonl"
_lock = Lock()


def log_event(event_type: str, **fields):
    entry = {"ts": datetime.now(timezone.utc).isoformat(), "type": event_type}
    for k, v in fields.items():
        if isinstance(v, str):
            v = redact_log(v)[:500]
        entry[k] = v
    line = json.dumps(entry, default=str)
    with _lock:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


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