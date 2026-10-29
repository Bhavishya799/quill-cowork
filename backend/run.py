"""Start the backend, killing any stale process on port 8000 first."""
import sys
from pathlib import Path


def _ensure_venv():
    """If we are not the venv Python and a venv exists, re-exec into it.

    This makes `python run.py` work regardless of which interpreter the
    user invoked, as long as backend/venv/ exists.
    """
    here = Path(__file__).resolve().parent
    if sys.platform == "win32":
        venv_python = here / "venv" / "Scripts" / "python.exe"
    else:
        venv_python = here / "venv" / "bin" / "python"

    try:
        current = Path(sys.executable).resolve()
    except Exception:
        return

    if current == venv_python.resolve() if venv_python.exists() else False:
        return

    if not venv_python.exists():
        return

    import subprocess
    print(f"[run] re-exec under venv: {venv_python}", flush=True)
    args = [str(venv_python), str(Path(__file__).resolve())] + sys.argv[1:]
    try:
        result = subprocess.run(args)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    _ensure_venv()


import socket
import subprocess
import sys
from pathlib import Path

PORT = 8000


def port_in_use(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return False
    except OSError:
        return True
    finally:
        s.close()


def kill_holder(port):
    r = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-NetTCPConnection -LocalPort {port} -State Listen "
         f"-ErrorAction SilentlyContinue | "
         f"Select-Object -ExpandProperty OwningProcess -Unique"],
        capture_output=True, text=True,
    )
    pids = [p.strip() for p in r.stdout.splitlines() if p.strip().isdigit()]
    for pid in pids:
        print(f"killing pid {pid} holding port {port}")
        subprocess.run(["taskkill", "/F", "/PID", pid],
                       capture_output=True, text=True)


def _check_search_backend():
    """Warn loudly if search cannot work in the interpreter that will serve."""
    try:
        import ddgs  # noqa: F401
        return
    except ImportError:
        pass
    print("=" * 60)
    print("WARNING: ddgs is not importable.")
    print("         Web search will show as 'off' in the UI.")
    print(f"         Fix: {sys.executable} -m pip install websift")
    print("=" * 60)


if __name__ == "__main__":
    if port_in_use(PORT):
        kill_holder(PORT)
    _check_search_backend()
    sys.path.insert(0, str(Path(__file__).parent))
    import uvicorn
    from config import settings
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)