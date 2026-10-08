"""Start the backend, killing any stale process on port 8000 first."""
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


if __name__ == "__main__":
    if port_in_use(PORT):
        kill_holder(PORT)
    sys.path.insert(0, str(Path(__file__).parent))
    import uvicorn
    from config import settings
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)