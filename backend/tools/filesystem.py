from pathlib import Path

from .registry import tool, connector


WORKSPACE = Path("D:/Quill-Cowork/workspace").resolve()


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
    pass


def _resolve(rel: str) -> Path:
    p = (WORKSPACE / rel).resolve()
    if not str(p).startswith(str(WORKSPACE)):
        raise ValueError(f"path outside workspace: {rel}")
    return p


@tool
def list_directory(path: str = ".") -> str:
    """List files and folders in a directory inside the workspace."""
    p = _resolve(path)
    if not p.is_dir():
        return f"not a directory: {path}"
    entries = [f"{'[DIR]' if i.is_dir() else '[FILE]'} {i.name}" for i in sorted(p.iterdir())]
    return "\n".join(entries) if entries else "(empty)"


@tool
def read_file(path: str) -> str:
    """Read a text file inside the workspace."""
    p = _resolve(path)
    if not p.is_file():
        return f"not a file: {path}"
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:8000]
    except Exception as e:
        return f"read failed: {e}"


@tool(destructive=True)
def write_file(path: str, content: str) -> str:
    """Write content to a file in the workspace. Overwrites if it exists."""
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars to {path}"


@tool
def search_files(pattern: str) -> str:
    """Search for files matching a glob pattern inside the workspace."""
    matches = [m for m in WORKSPACE.rglob(pattern) if m != WORKSPACE]
    if not matches:
        return f"no files match '{pattern}'"
    return "\n".join(str(m.relative_to(WORKSPACE)) for m in matches[:50])