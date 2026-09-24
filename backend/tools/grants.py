"""Folder grant tools — what the AI sees."""
from pathlib import Path

from .registry import tool, connector
import grants as grants_mod


@connector({
    "id": "grants",
    "name": "Folder Grants",
    "description": "User-approved folders outside the workspace sandbox",
    "accent": "#8B5CF6",
    "widgets": [],
    "quick_actions": [
        {"label": "List granted folders", "prompt": "List my granted folders"},
    ],
})
class GrantsConnector:
    pass


@tool
def list_grants() -> str:
    """List folders the user has granted read/write access to. These live
    outside the workspace sandbox. Use list_directory / read_file /
    write_file on absolute paths inside these folders."""
    entries = grants_mod.list_grants()
    if not entries:
        return ("No folders granted yet. Ask the user to grant a folder via "
                "request_folder_grant, or they can add one from Profile.")
    lines = []
    for e in entries:
        perms = []
        if e.get("read"):
            perms.append("read")
        if e.get("write"):
            perms.append("write")
        lines.append(f"- {e['path']} ({'/'.join(perms) or 'none'})")
    return "\n".join(lines)


@tool(destructive=True)
def request_folder_grant(path: str) -> str:
    """Ask the user to grant read/write access to a folder outside the
    workspace sandbox. The user will be prompted to approve or deny.
    Only call this when the user has explicitly asked to work on a
    specific folder. Use an absolute path."""
    raw = str(path or "").strip()
    if not raw:
        return "grant failed: no path provided"
    try:
        resolved = Path(raw).expanduser().resolve()
    except Exception as e:
        return f"grant failed: invalid path ({e})"
    if not resolved.exists():
        return f"grant failed: path does not exist ({resolved})"
    if not resolved.is_dir():
        return f"grant failed: not a folder ({resolved})"

    refused = grants_mod.is_hard_refused(str(resolved))
    if refused:
        return (f"grant refused: {resolved} contains '{refused}' — this path "
                f"is never grantable via the AI. The user can add it manually "
                f"from the Profile panel if they understand the risk.")

    entry = grants_mod.add_grant(str(resolved), label=resolved.name,
                                  read=True, write=True)
    return f"granted: {entry['path']} (read + write)"