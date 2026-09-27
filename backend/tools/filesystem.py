import os
from pathlib import Path

from .registry import tool, connector
import grants


WORKSPACE = Path(os.getenv("WORKSPACE_ROOT", "D:/Quill-Cowork/workspace")).resolve()


@connector({
    "id": "filesystem",
    "name": "Filesystem",
    "description": "Local file access inside the workspace and granted folders",
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


_ROOT_ALIASES = {".", "/", "", "workspace", "/workspace", "\\workspace",
                 "./workspace", ".\\workspace", "the workspace",
                 "the workspace root", "workspace root", "workspace/"}


def _resolve(rel: str, write: bool = False) -> Path:
    raw = str(rel or "").strip()
    if raw in _ROOT_ALIASES or raw.lower() in _ROOT_ALIASES:
        return WORKSPACE

    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (WORKSPACE / raw).resolve()
    else:
        p = p.resolve()

    if p.is_relative_to(WORKSPACE):
        return p

    grant = grants.resolve_under_grants(p)
    if grant:
        if write and not grant.get("write"):
            raise ValueError(f"no write permission for granted folder: {grant['path']}")
        if not write and not grant.get("read"):
            raise ValueError(f"no read permission for granted folder: {grant['path']}")
        return p

    raise ValueError(
        f"path outside workspace and not in any granted folder: {rel} "
        f"(workspace is {WORKSPACE})"
    )


@tool
def list_directory(path: str = ".") -> str:
    """List files and folders in a directory inside the workspace or a granted folder.
    Defaults to the workspace root. Use '.' for the workspace root."""
    try:
        p = _resolve(path)
    except ValueError as e:
        return (f"cannot list '{path}': {e}. Use '.' to list the workspace root.")
    if not p.exists():
        return f"path does not exist: {path} (resolved to {p})"
    if not p.is_dir():
        return f"not a directory: {path} (resolved to {p})"
    try:
        entries = [f"{'[DIR]' if i.is_dir() else '[FILE]'} {i.name}"
                   for i in sorted(p.iterdir())]
    except Exception as e:
        return f"read failed: {e}"
    return "\n".join(entries) if entries else "(empty)"


@tool
def read_file(path: str) -> str:
    """Read a text file inside the workspace or a granted folder."""
    try:
        p = _resolve(path)
    except ValueError as e:
        return f"cannot read '{path}': {e}"
    if not p.exists():
        return f"file does not exist: {path} (resolved to {p})"
    if not p.is_file():
        return f"not a file: {path} (resolved to {p})"
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:8000]
    except Exception as e:
        return f"read failed: {e}"


@tool(destructive=True)
def write_file(path: str, content: str) -> str:
    """Write content to a file in the workspace or a granted folder."""
    try:
        p = _resolve(path, write=True)
    except ValueError as e:
        return f"cannot write '{path}': {e}"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars to {path}"


@tool
def search_files(pattern: str, path: str = ".") -> str:
    """Search for files matching a glob pattern."""
    try:
        base = _resolve(path)
    except ValueError as e:
        return f"cannot search '{path}': {e}"
    if not base.is_dir():
        return f"not a directory: {path} (resolved to {base})"
    try:
        matches = [m for m in base.rglob(pattern) if m.is_file()]
    except Exception as e:
        return f"search failed: {e}"
    if not matches:
        return f"no files match '{pattern}'"
    try:
        return "\n".join(str(m.relative_to(base)) for m in matches[:50])
    except Exception:
        return "\n".join(str(m) for m in matches[:50])