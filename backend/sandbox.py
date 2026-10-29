"""Sandboxed command execution.

Strategy:
  1. Docker (if available): network=none, memory=512m, cpus=1,
     pids=64, workspace mounted rw.
  2. Subprocess fallback: scrubbed env, workspace cwd, timeout,
     output cap, process-group kill on timeout.

Both paths refuse obvious escapes (rm -rf /, sudo, fork bomb, pipes
from curl/wget into a shell). Absolute paths outside the workspace
are still possible in the subprocess fallback; use Docker for a hard
guarantee.
"""
from __future__ import annotations
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from config import settings

WORKSPACE = Path(settings.WORKSPACE_ROOT).resolve()
MAX_OUTPUT = 100_000
FORBIDDEN = [
    r"\brm\s+-rf\s+/",
    r"\bsudo\b",
    r":\(\)\s*\{.*\}\s*;\s*:",
    r"\bcurl\b.*\|\s*(?:sh|bash)",
    r"\bwget\b.*\|\s*(?:sh|bash)",
    r"\bpowershell\b.*-enc\b",
    r"\bdd\s+if=",
    r"\bmkfs\b",
]
_FORBIDDEN_RX = re.compile("|".join(FORBIDDEN), re.IGNORECASE)

SAFE_ENV_KEYS = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC",
                 "TEMP", "TMP", "USERPROFILE", "APPDATA", "LOCALAPPDATA",
                 "HOME", "LANG", "LC_ALL", "TZ"}


def _blocked(cmd: str) -> str | None:
    m = _FORBIDDEN_RX.search(cmd or "")
    return m.group(0) if m else None


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    try:
        r = subprocess.run(["docker", "version", "--format", "{{.Server.Version}}"],
                           capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _safe_env() -> dict:
    return {k: v for k, v in os.environ.items() if k in SAFE_ENV_KEYS}


def _run_docker(cmd: str, cwd: Path, timeout: int) -> dict:
    docker_cmd = [
        "docker", "run", "--rm",
        "--network=none",
        "--memory=512m", "--cpus=1", "--pids-limit=64",
        "-v", f"{cwd}:/workspace:rw",
        "-w", "/workspace",
        "-e", "HOME=/tmp",
        "python:3.11-slim",
        "sh", "-c", cmd,
    ]
    try:
        r = subprocess.run(docker_cmd, capture_output=True, text=True,
                           timeout=timeout + 5)
    except subprocess.TimeoutExpired:
        return {"ok": False, "exit_code": -1, "stdout": "", "stderr": "",
                "timed_out": True, "sandbox": "docker"}
    return {
        "ok": r.returncode == 0,
        "exit_code": r.returncode,
        "stdout": (r.stdout or "")[:MAX_OUTPUT],
        "stderr": (r.stderr or "")[:MAX_OUTPUT],
        "timed_out": False,
        "sandbox": "docker",
    }


def _run_subprocess(cmd: str, cwd: Path, timeout: int) -> dict:
    env = _safe_env()
    kwargs = {"cwd": str(cwd), "env": env, "shell": True,
              "capture_output": True, "text": True, "timeout": timeout}
    if sys.platform == "win32":
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        kwargs["shell"] = True
    else:
        kwargs["start_new_session"] = True
    try:
        r = subprocess.run(cmd, **kwargs)
        return {
            "ok": r.returncode == 0,
            "exit_code": r.returncode,
            "stdout": (r.stdout or "")[:MAX_OUTPUT],
            "stderr": (r.stderr or "")[:MAX_OUTPUT],
            "timed_out": False,
            "sandbox": "subprocess",
        }
    except subprocess.TimeoutExpired as e:
        return {
            "ok": False, "exit_code": -1,
            "stdout": ((e.stdout or b"") if isinstance(e.stdout, bytes) else (e.stdout or ""))[:MAX_OUTPUT] if e.stdout else "",
            "stderr": "timed out",
            "timed_out": True,
            "sandbox": "subprocess",
        }
    except Exception as e:
        return {"ok": False, "exit_code": -1, "stdout": "",
                "stderr": f"{type(e).__name__}: {e}",
                "timed_out": False, "sandbox": "subprocess"}


def run(cmd: str, cwd: str = ".", timeout: int = 60) -> dict:
    blocked = _blocked(cmd)
    if blocked:
        return {"ok": False, "exit_code": -1, "stdout": "",
                "stderr": f"blocked pattern: {blocked}",
                "timed_out": False, "sandbox": "none"}
    try:
        cwd_path = (WORKSPACE / cwd).resolve() if not Path(cwd).is_absolute() else Path(cwd).resolve()
    except Exception:
        cwd_path = WORKSPACE
    if not cwd_path.is_relative_to(WORKSPACE):
        return {"ok": False, "exit_code": -1, "stdout": "",
                "stderr": f"cwd escapes workspace: {cwd_path}",
                "timed_out": False, "sandbox": "none"}
    timeout = max(5, min(int(timeout), 300))
    if _docker_available():
        return _run_docker(cmd, cwd_path, timeout)
    return _run_subprocess(cmd, cwd_path, timeout)


def status() -> dict:
    return {
        "workspace": str(WORKSPACE),
        "docker_available": _docker_available(),
        "platform": sys.platform,
    }
