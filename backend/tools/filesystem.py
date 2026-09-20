"""Filesystem tools — sandboxed file access."""

from pathlib import Path

from .registry import tool, connector


WORKSPACE = (Path(__file__).parent.parent.parent / "workspace").resolve()


def _safe_path(rel: str) -> Path:
    p = (WORKSPACE / rel).resolve()
    if not str(p).startswith(str(WORKSPACE)):
        raise ValueError(f"Path outside workspace: {rel}")
    return p


@connector({
    "id": "filesystem",
    "name": "Filesystem",
    "description": "Local file access inside the workspace sandbox",
    "accent": "#14B8A6",
    "widgets": [
        {"type": "counter", "id": "files", "label": "Workspace", "tool": "list_directory"},
    ],
    "quick_actions": [
        {"label": "List workspace", "prompt": "List the files in my workspace folder"},
        {"label": "Read notes", "prompt": "Read notes.txt and summarize it"},
    ],
})
class FilesystemConnector:
    """Declares the filesystem connector manifest."""
    pass


@tool
def list_directory(path: str = ".") -> str:
    """List files and folders in a directory inside the workspace."""
    p = _safe_path(path)
    if not p.exists():
        return f"Directory does not exist: {path}"
    if not p.is_dir():
        return f"Not a directory: {path}"
    entries = []
    for item in sorted(p.iterdir()):
        kind = "[DIR]" if item.is_dir() else "[FILE]"
        entries.append(f"{kind} {item.name}")
    return "\n".join(entries) if entries else "(empty directory)"


@tool
def read_file(path: str) -> str:
    """Read the contents of a text file inside the workspace."""
    p = _safe_path(path)
    if not p.exists():
        return f"File does not exist: {path}"
    if not p.is_file():
        return f"Not a file: {path}"
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:8000]
    except Exception as e:
        return f"Could not read file: {e}"


@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file in the workspace. Overwrites if exists."""
    p = _safe_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} chars to {path}"


@tool
def search_files(pattern: str) -> str:
    """Search for files matching a glob pattern (e.g. '*.txt') in the workspace."""
    matches = list(WORKSPACE.rglob(pattern))
    if not matches:
        return f"No files match '{pattern}'"
    return "\n".join(str(m.relative_to(WORKSPACE)) for m in matches[:50])