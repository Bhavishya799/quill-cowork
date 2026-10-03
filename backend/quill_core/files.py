"""File utilities.

Binary detection: null-byte check first, then chardet with a confidence
threshold. Falls back to a printable-ratio heuristic if chardet is not
installed, so the package works without the dependency.
"""
from pathlib import Path

SAMPLE_BYTES = 8192
PRINTABLE_FALLBACK = 0.85
MIN_CONFIDENCE = 0.5


def is_binary(path: Path, sample_bytes: int = SAMPLE_BYTES) -> bool:
    """Return True if the file looks binary.

    Order of checks:
      1. Read error -> binary (fail closed on unreadable).
      2. Empty file -> not binary.
      3. Null byte present -> binary.
      4. chardet detects encoding with confidence >= 0.5 -> text.
      5. chardet gives up or low confidence -> binary.
      6. chardet missing -> printable-ratio fallback.
    """
    try:
        raw = path.read_bytes()[:sample_bytes]
    except Exception:
        return True
    if not raw:
        return False
    if b"\x00" in raw:
        return True
    try:
        import chardet
        result = chardet.detect(raw) or {}
        enc = result.get("encoding")
        conf = float(result.get("confidence") or 0.0)
        if enc is None:
            return True
        return conf < MIN_CONFIDENCE
    except Exception:
        printable = sum(1 for b in raw if 32 <= b < 127 or b in (9, 10, 13))
        return (printable / len(raw)) < PRINTABLE_FALLBACK
