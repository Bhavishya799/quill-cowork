"""Obsidian connector. Reads and writes a local vault folder.

The vault is a directory of markdown files. This module treats it as
first-class note storage: it parses frontmatter, extracts inline tags
and wikilinks, and supports the daily-note convention.

Configuration:
    Set OBSIDIAN_VAULT to the vault folder, in .env or the vault:
        python vault.py set OBSIDIAN_VAULT "C:/Users/you/Documents/MyVault" --sensitive
"""
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .registry import tool, connector
from vault import vault


MAX_NOTE_CHARS = 20000
MAX_SEARCH_HITS = 40
DAILY_FOLDER = ""  # relative to vault root; empty means vault root


@connector({
    "id": "obsidian",
    "name": "Obsidian",
    "description": "Read, write, and search an Obsidian vault",
    "accent": "#7C3AED",
    "widgets": [],
    "quick_actions": [
        {"label": "List notes", "prompt": "List my Obsidian notes"},
        {"label": "Today's daily note", "prompt": "Open today's daily note"},
    ],
})
class ObsidianConnector:
    pass


# ---------------------------------------------------------------------
# Configuration and path safety
# ---------------------------------------------------------------------

def _vault_root() -> Optional[Path]:
    raw = (vault.get_safe("OBSIDIAN_VAULT")
           or os.getenv("OBSIDIAN_VAULT", "")).strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    if not p.is_dir():
        return None
    return p.resolve()


def _no_vault_msg() -> str:
    return ("Obsidian vault not configured. Set OBSIDIAN_VAULT in .env "
            "or run: python vault.py set OBSIDIAN_VAULT "
            "'C:/path/to/vault' --sensitive")


def _safe_note(rel: str) -> Path:
    root = _vault_root()
    if root is None:
        raise RuntimeError(_no_vault_msg())
    rel = (rel or "").strip().lstrip("/\\")
    if not rel:
        raise ValueError("empty note name")
    if not rel.lower().endswith(".md"):
        rel = rel + ".md"
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"path escapes vault: {rel}")
    return target


def _iter_notes(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d != "node_modules"]
        for f in filenames:
            if f.lower().endswith(".md"):
                yield Path(dirpath) / f


# ---------------------------------------------------------------------
# Markdown parsing
# ---------------------------------------------------------------------

def _parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, text
    fm_raw = text[4:end]
    body = text[end + 5:]
    fm: Dict[str, str] = {}
    for line in fm_raw.splitlines():
        if ":" in line and not line.strip().startswith("#"):
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip().strip('"').strip("'")
    return fm, body


_TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z0-9_\-/]+)")
_LINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")


def _extract_tags(text: str) -> List[str]:
    # Strip fenced code blocks first so code does not pollute tags
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return sorted(set(_TAG_RE.findall(text)))


def _extract_links(text: str) -> List[str]:
    return sorted(set(m.strip() for m in _LINK_RE.findall(text)))


# ---------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------

@tool
def obsidian_list_notes(folder: str = "", limit: int = 100) -> str:
    """List markdown notes in the Obsidian vault.
    folder: optional subfolder to list. Empty means the whole vault."""
    root = _vault_root()
    if root is None:
        return _no_vault_msg()

    base = root
    if folder:
        candidate = (root / folder.strip().lstrip("/\\")).resolve()
        if not candidate.is_relative_to(root):
            return f"folder escapes vault: {folder}"
        if not candidate.is_dir():
            return f"not a folder in vault: {folder}"
        base = candidate

    notes: List[str] = []
    for p in _iter_notes(base):
        notes.append(str(p.relative_to(root)).replace("\\", "/"))
        if len(notes) >= limit:
            break

    if not notes:
        return f"no notes in {folder or 'vault'}"
    notes.sort()
    out = "\n".join(f"- {n}" for n in notes)
    if len(notes) == limit:
        out += f"\n(stopped at {limit}; narrow the folder or raise limit)"
    return out


@tool
def obsidian_read_note(name: str) -> str:
    """Read a note by name. Returns frontmatter, tags, wikilinks, and body.
    name: relative path inside the vault, with or without .md"""
    try:
        p = _safe_note(name)
    except (RuntimeError, ValueError) as e:
        return str(e)
    if not p.is_file():
        return f"note not found: {name}"
    text = p.read_text(encoding="utf-8", errors="replace")
    fm, body = _parse_frontmatter(text)
    tags = _extract_tags(body)
    links = _extract_links(body)

    header = [f"# {p.name}"]
    if fm:
        header.append("frontmatter:")
        for k, v in fm.items():
            header.append(f"  {k}: {v}")
    if tags:
        header.append(f"tags: {', '.join(tags)}")
    if links:
        header.append(f"links: {', '.join(links[:20])}")

    if len(body) > MAX_NOTE_CHARS:
        body = body[:MAX_NOTE_CHARS] + "\n[...truncated]"
    return "\n".join(header) + "\n\n" + body


@tool(destructive=True)
def obsidian_write_note(name: str, content: str) -> str:
    """Create or overwrite an Obsidian note. User is prompted before writing.
    name: relative path inside the vault, with or without .md"""
    try:
        p = _safe_note(name)
    except (RuntimeError, ValueError) as e:
        return str(e)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars to {p.name}"


@tool(destructive=True)
def obsidian_append_note(name: str, content: str) -> str:
    """Append content to an existing note, or create it if missing.
    Adds a blank line before the appended block unless the note is empty.
    User is prompted before writing."""
    try:
        p = _safe_note(name)
    except (RuntimeError, ValueError) as e:
        return str(e)
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = p.read_text(encoding="utf-8", errors="replace") if p.is_file() else ""
    sep = "" if not existing else ("\n" if existing.endswith("\n") else "\n\n")
    p.write_text(existing + sep + content, encoding="utf-8")
    verb = "appended to" if existing else "created"
    return f"{verb} {p.name} ({len(content)} chars)"


@tool
def obsidian_search(query: str, limit: int = 20) -> str:
    """Search note bodies across the vault. Case-insensitive substring match.
    Returns path:line hits."""
    root = _vault_root()
    if root is None:
        return _no_vault_msg()
    q = (query or "").strip().lower()
    if not q:
        return "empty query"

    hits: List[str] = []
    for p in _iter_notes(root):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if q in line.lower():
                snippet = line.strip()[:140]
                hits.append(f"{p.relative_to(root)}:{i}: {snippet}")
                if len(hits) >= limit:
                    break
        if len(hits) >= limit:
            break

    if not hits:
        return f"no matches for '{query}'"
    return "\n".join(hits)


@tool
def obsidian_list_tags() -> str:
    """List every inline #tag in the vault with a count of how many notes use it."""
    root = _vault_root()
    if root is None:
        return _no_vault_msg()

    counts: Dict[str, int] = {}
    for p in _iter_notes(root):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for t in _extract_tags(text):
            counts[t] = counts.get(t, 0) + 1

    if not counts:
        return "no tags found"
    ordered = sorted(counts.items(), key=lambda x: (-x[1], x[0]))
    return "\n".join(f"- #{t}  ({n})" for t, n in ordered[:100])


@tool
def obsidian_backlinks(name: str) -> str:
    """Find notes that link to the given note via [[wikilink]].
    name: note name without extension, or relative path."""
    root = _vault_root()
    if root is None:
        return _no_vault_msg()

    stem = Path(name).stem.lower()
    sources: List[str] = []
    for p in _iter_notes(root):
        if p.stem.lower() == stem:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for link in _extract_links(text):
            if Path(link).stem.lower() == stem:
                sources.append(str(p.relative_to(root)).replace("\\", "/"))
                break

    if not sources:
        return f"no backlinks to '{name}'"
    return "\n".join(f"- {s}" for s in sorted(set(sources)))


@tool
def obsidian_daily_note(date: str = "today") -> str:
    """Read the daily note for a date, creating it if missing.
    date: 'today', 'yesterday', or 'YYYY-MM-DD'."""
    root = _vault_root()
    if root is None:
        return _no_vault_msg()

    d = date.strip().lower()
    if d == "today" or not d:
        target_date = datetime.now().date()
    elif d == "yesterday":
        target_date = datetime.now().date() - timedelta(days=1)
    else:
        try:
            target_date = datetime.strptime(d, "%Y-%m-%d").date()
        except ValueError:
            return f"bad date: {date} (use YYYY-MM-DD or 'today'/'yesterday')"

    fname = target_date.strftime("%Y-%m-%d") + ".md"
    rel = f"{DAILY_FOLDER}/{fname}" if DAILY_FOLDER else fname
    p = (root / rel).resolve()
    if not p.is_relative_to(root):
        return "daily note path escapes vault"

    if not p.is_file():
        p.parent.mkdir(parents=True, exist_ok=True)
        heading = target_date.strftime("%A, %d %B %Y")
        p.write_text(f"# {heading}\n\n", encoding="utf-8")
        return f"created daily note {rel}\n\n# {heading}\n"

    text = p.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_NOTE_CHARS:
        text = text[:MAX_NOTE_CHARS] + "\n[...truncated]"
    return f"{rel}\n\n{text}"
