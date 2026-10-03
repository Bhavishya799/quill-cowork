"""Markdown utilities.

Self-contained. No PyYAML, no third-party YAML loader. Handles the flat
key:value frontmatter that Obsidian users actually write. Nested maps
and anchor/alias syntax are not supported; if you need them, install
python-frontmatter yourself after verifying its loader uses
yaml.safe_load.
"""
import re
from typing import Dict, List, Tuple

_TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z0-9_\-/]+)")
_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_FM_OPEN_RE = re.compile(r"^---\r?\n")
_FM_CLOSE_RE = re.compile(r"\r?\n---\r?\n")


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Parse flat YAML frontmatter. Returns (metadata, body).

    Only handles lines of the form `key: value`. Values are coerced to
    strings. Quoted values have one layer of quotes stripped.
    """
    if not text:
        return {}, text
    open_m = _FM_OPEN_RE.match(text)
    if not open_m:
        return {}, text
    close_m = _FM_CLOSE_RE.search(text, open_m.end())
    if not close_m:
        return {}, text
    fm_raw = text[open_m.end():close_m.start()]
    body = text[close_m.end():]
    fm: Dict[str, str] = {}
    for line in fm_raw.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if ":" not in s:
            continue
        k, v = s.split(":", 1)
        key = k.strip()
        val = v.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("\"", "'"):
            val = val[1:-1]
        fm[key] = val
    return fm, body


def extract_tags(text: str) -> List[str]:
    """Inline #tag extraction. Fenced code blocks are stripped first."""
    if not text:
        return []
    stripped = _FENCE_RE.sub("", text)
    return sorted(set(_TAG_RE.findall(stripped)))


def extract_links(text: str) -> List[str]:
    """Wikilink extraction. Returns the target of each [[link|alias]]."""
    if not text:
        return []
    return sorted(set(m.strip() for m in _LINK_RE.findall(text)))
