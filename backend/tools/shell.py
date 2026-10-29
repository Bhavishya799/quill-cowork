"""Sandboxed shell command execution tool."""
import os
from .registry import tool, connector
import sandbox


@connector({
    "id": "shell",
    "name": "Shell",
    "description": "Sandboxed shell command execution (opt-in)",
    "accent": "#DC2626",
    "widgets": [],
    "quick_actions": [
        {"label": "Run tests", "prompt": "run pytest in the workspace"},
    ],
})
class ShellConnector:
    pass


@tool(destructive=True, safety={"writes_files": True})
def run_command(cmd: str, cwd: str = ".", timeout: int = 60) -> str:
    """Run a shell command inside a sandbox (Docker if available,
    subprocess fallback). Returns exit code, stdout, stderr.
    Requires ENABLE_RUN_COMMAND=1 in backend/.env."""
    if os.getenv("ENABLE_RUN_COMMAND", "0") != "1":
        return ("run_command is disabled. Set ENABLE_RUN_COMMAND=1 in "
                "backend/.env and restart the server.")
    r = sandbox.run(cmd, cwd=cwd, timeout=timeout)
    return (
        f"exit_code: {r['exit_code']}\n"
        f"sandbox: {r['sandbox']}\n"
        f"timed_out: {r['timed_out']}\n"
        f"--- stdout ---\n{r['stdout']}\n"
        f"--- stderr ---\n{r['stderr']}"
    )
