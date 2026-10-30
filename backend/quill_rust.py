"""
quill_rust.py - single-file Rust bridge for Quill-Cowork.

Embeds Cargo.toml and src/main.rs, builds a release binary on first
use, and patches the hot paths in codebase.py, tools/filesystem.py,
and agent.py to delegate to the binary.

Usage:
    cd backend && python quill_rust.py          # build (if needed) + run server
    cd backend && python quill_rust.py build    # build only

The server still runs from main:app via uvicorn, exactly as before.
If the binary is not present, Quill-Cowork falls back to pure Python
and prints a one-line warning.
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent.resolve()
BACKEND_DIR = HERE
BUILD_DIR = HERE.parent / "rust_core"
BIN_NAME = "quill_core.exe" if platform.system() == "Windows" else "quill_core"
BIN_PATH = BUILD_DIR / "target" / "release" / BIN_NAME

def _index_root() -> Path:
    raw = os.getenv("WORKSPACE_ROOT", str(BACKEND_DIR / "workspace"))
    return Path(raw).resolve() / ".quill" / "codebases"


def _workspace() -> Path:
    raw = os.getenv("WORKSPACE_ROOT", str(BACKEND_DIR / "workspace"))
    return Path(raw).resolve()


def binary_path() -> Path:
    return BIN_PATH


def is_built() -> bool:
    return BIN_PATH.exists()


def _call(args, stdin_payload=None, timeout=120):
    if not BIN_PATH.exists():
        raise RuntimeError(
            f"quill_core binary not built at {BIN_PATH}; run: python quill_rust.py build"
        )
    input_data = None
    if stdin_payload is not None:
        input_data = json.dumps(stdin_payload)
    try:
        r = subprocess.run(
            [str(BIN_PATH)] + args,
            capture_output=True, text=True,
            input=input_data, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"quill_core timed out after {timeout}s")
    if r.returncode != 0:
        raise RuntimeError(f"quill_core failed: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout


def _grants_json():
    try:
        import grants as _g
        return json.dumps([{"path": g["path"], "read": bool(g.get("read")),
                            "write": bool(g.get("write"))} for g in _g.list_grants()])
    except Exception:
        return "[]"


def _wrap_ingest(root, name=""):
    out = _call(["ingest", "--root", str(root), "--name", name or "",
                 "--index-root", str(_index_root())], timeout=300)
    return json.loads(out)


def _wrap_list_codebases():
    out = _call(["list", "--index-root", str(_index_root())])
    return json.loads(out)


def _wrap_get_meta(name):
    if not name:
        return None
    try:
        out = _call(["meta", "--index-root", str(_index_root()), "--name", name])
        return json.loads(out)
    except Exception:
        return None


def _wrap_disconnect(name):
    out = _call(["disconnect", "--index-root", str(_index_root()), "--name", name])
    return bool(json.loads(out).get("ok"))


def _wrap_get_summary(name, max_chars=3500):
    try:
        return _call(["summary", "--index-root", str(_index_root()),
                      "--name", name, "--max-chars", str(max_chars)])
    except Exception:
        return f"no index for '{name}'"


def _wrap_get_tree(name, max_lines=400):
    try:
        return _call(["tree", "--index-root", str(_index_root()),
                      "--name", name, "--max-lines", str(max_lines)])
    except Exception:
        return f"no index for '{name}'"


def _wrap_search(name, query, limit=15):
    try:
        return _call(["search", "--index-root", str(_index_root()),
                      "--name", name, "--query", query, "--limit", str(limit)])
    except Exception as e:
        return f"search failed: {e}"


def _wrap_grep(name, pattern, limit=40):
    try:
        return _call(["grep", "--index-root", str(_index_root()),
                      "--name", name, "--pattern", pattern, "--limit", str(limit)])
    except Exception as e:
        return f"grep failed: {e}"


def _wrap_read_file(name, path, max_chars=8000):
    try:
        return _call(["read", "--index-root", str(_index_root()),
                      "--name", name, "--path", path, "--max-chars", str(max_chars)])
    except Exception as e:
        return f"read failed: {e}"


def _wrap_read_all(name, max_chars=200_000):
    try:
        return _call(["readall", "--index-root", str(_index_root()),
                      "--name", name, "--max-chars", str(max_chars)])
    except Exception as e:
        return f"read all failed: {e}"


def _wrap_symbols(name, kind="all", limit=400):
    try:
        return _call(["symbols", "--index-root", str(_index_root()),
                      "--name", name, "--kind", kind, "--limit", str(limit)])
    except Exception as e:
        return f"symbols failed: {e}"


def _wrap_find_symbol(name, symbol):
    try:
        return _call(["findsym", "--index-root", str(_index_root()),
                      "--name", name, "--symbol", symbol])
    except Exception as e:
        return f"find symbol failed: {e}"


def _wrap_imports(name, path, direction="out"):
    try:
        return _call(["imports", "--index-root", str(_index_root()),
                      "--name", name, "--file", path, "--direction", direction])
    except Exception as e:
        return f"imports failed: {e}"


def _wrap_write_file(name, path, content):
    try:
        return _call(["write", "--index-root", str(_index_root())],
                     stdin_payload={"name": name, "path": path, "content": content})
    except Exception as e:
        return f"write failed: {e}"


def _wrap_patch_file(name, path, find, replace, count=1):
    try:
        return _call(["patch", "--index-root", str(_index_root())],
                     stdin_payload={"name": name, "path": path,
                                    "find": find, "replace": replace,
                                    "count": int(count)})
    except Exception as e:
        return f"patch failed: {e}"


def _wrap_git_status(name):
    meta = _wrap_get_meta(name)
    if not meta:
        return f"no codebase named '{name}'"
    try:
        return _call(["gitstatus", "--root", meta["root"]])
    except Exception as e:
        return f"git status failed: {e}"


def _wrap_git_commit(name, message):
    meta = _wrap_get_meta(name)
    if not meta:
        return f"no codebase named '{name}'"
    try:
        return _call(["gitcommit", "--root", meta["root"], "--message", message])
    except Exception as e:
        return f"git commit failed: {e}"


def _wrap_git_push(name, remote="origin", branch=""):
    meta = _wrap_get_meta(name)
    if not meta:
        return f"no codebase named '{name}'"
    try:
        from vault import vault
        token = vault.get_safe("GITHUB_PERSONAL_ACCESS_TOKEN") or ""
    except Exception:
        token = ""
    try:
        return _call(["gitpush", "--root", meta["root"],
                      "--remote", remote, "--branch", branch, "--token", token],
                     timeout=180)
    except Exception as e:
        return f"push failed: {e}"


def _wrap_fs_list_directory(path="."):
    return _call(["fslist", "--workspace", str(_workspace()),
                  "--path", path, "--grants", _grants_json()])


def _wrap_fs_read_file(path):
    return _call(["fsread", "--workspace", str(_workspace()),
                  "--path", path, "--grants", _grants_json()])


def _wrap_fs_write_file(path, content):
    return _call(["fswrite", "--workspace", str(_workspace()),
                  "--grants", _grants_json()],
                 stdin_payload={"path": path, "content": content})


def _wrap_fs_search_files(pattern, path="."):
    return _call(["fssearch", "--workspace", str(_workspace()),
                  "--path", path, "--pattern", pattern,
                  "--grants", _grants_json()])


def _wrap_filter_tools(message: str, all_tools: list, session_id: str = "") -> list:
    try:
        import agent
        recent_search = False
        if session_id:
            _ts = agent._RECENT_SEARCH.get(session_id, 0.0)
            if _ts and (time.time() - _ts) < agent._RECENT_SEARCH_TTL:
                recent_search = True
                
        tool_names = [t["function"]["name"] for t in all_tools]
        payload = {
            "message": message,
            "tool_names": tool_names,
            "recent_search": recent_search
        }
        out = _call(["route"], stdin_payload=payload)
        keep_names = json.loads(out)
        keep_set = set(keep_names)
        return [t for t in all_tools if t["function"]["name"] in keep_set]
    except Exception as e:
        print(f"[quill_rust] route failed: {e}, falling back to python")
        import agent
        if hasattr(agent, "_original_filter_tools"):
            return agent._original_filter_tools(message, all_tools, session_id=session_id)
        return []


def build(force=False):
    if BIN_PATH.exists() and not force:
        print(f"[quill_rust] binary already present: {BIN_PATH}")
        return True
    if not shutil.which("cargo"):
        print("[quill_rust] cargo not found on PATH. Install Rust from https://rustup.rs and retry.")
        return False
    print(f"[quill_rust] building in {BUILD_DIR} (this can take a few minutes on first run)")
    r = subprocess.run(
        ["cargo", "build", "--release"],
        cwd=str(BUILD_DIR),
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        print("[quill_rust] cargo build failed:")
        print((r.stderr or r.stdout or "").strip()[:2000])
        return False
    if not BIN_PATH.exists():
        print(f"[quill_rust] build succeeded but binary not found at {BIN_PATH}")
        return False
    print(f"[quill_rust] built: {BIN_PATH}")
    return True


def install():
    if not BIN_PATH.exists():
        print(f"[quill_rust] binary not built at {BIN_PATH}; Quill-Cowork will run in pure-Python mode")
        print("[quill_rust] build it with: python quill_rust.py build")
        return False
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    try:
        import codebase as cb
        import tools.filesystem as fs
        import tools.registry as reg
        import agent
        from tools import load_all_tools
        try:
            load_all_tools()
        except Exception:
            pass
    except Exception as e:
        print(f"[quill_rust] install failed (import error): {e}")
        return False

    cb.ingest = _wrap_ingest
    cb.list_codebases = _wrap_list_codebases
    cb.get_meta = _wrap_get_meta
    cb.disconnect = _wrap_disconnect
    cb.get_summary = _wrap_get_summary
    cb.get_tree = _wrap_get_tree
    cb.search = _wrap_search
    cb.grep = _wrap_grep
    cb.read_file = _wrap_read_file
    cb.read_all = _wrap_read_all
    cb.symbols = _wrap_symbols
    cb.find_symbol = _wrap_find_symbol
    cb.imports = _wrap_imports
    cb.write_file = _wrap_write_file
    cb.patch_file = _wrap_patch_file
    cb.git_status = _wrap_git_status
    cb.git_commit = _wrap_git_commit
    cb.git_push = _wrap_git_push

    fs.list_directory = _wrap_fs_list_directory
    fs.read_file = _wrap_fs_read_file
    fs.write_file = _wrap_fs_write_file
    fs.search_files = _wrap_fs_search_files

    if not hasattr(agent, "_original_filter_tools"):
        agent._original_filter_tools = agent.filter_tools
        agent.filter_tools = _wrap_filter_tools

    for tool_name, func in [
        ("list_codebases", _wrap_list_codebases),
        ("disconnect_codebase", lambda name: (
            f"disconnected: {name}" if _wrap_disconnect(name) else f"no codebase named '{name}'")),
        ("codebase_tree", lambda name: _wrap_get_tree(name, 500)),
        ("codebase_search", _wrap_search),
        ("codebase_grep", _wrap_grep),
        ("codebase_read", _wrap_read_file),
        ("codebase_read_all", _wrap_read_all),
        ("codebase_symbols", _wrap_symbols),
        ("codebase_find_symbol", _wrap_find_symbol),
        ("codebase_imports", _wrap_imports),
        ("codebase_write", _wrap_write_file),
        ("codebase_patch", _wrap_patch_file),
    ]:
        if tool_name in reg._tools:
            reg._tools[tool_name]["function"] = func

    for tool_name, func in [
        ("list_directory", _wrap_fs_list_directory),
        ("read_file", _wrap_fs_read_file),
        ("write_file", _wrap_fs_write_file),
        ("search_files", _wrap_fs_search_files),
    ]:
        if tool_name in reg._tools:
            reg._tools[tool_name]["function"] = func

    print("[quill_rust] installed: codebase + filesystem + agent routing delegate to quill_core")
    return True


def run():
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))
    os.chdir(BACKEND_DIR)
    install()
    import uvicorn
    from config import settings
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "build":
        ok = build(force="--force" in sys.argv)
        sys.exit(0 if ok else 1)
    elif cmd == "run":
        run()
    elif cmd == "install":
        sys.exit(0 if install() else 1)
    else:
        if not build():
            print("[quill_rust] build failed; aborting")
            sys.exit(1)
        run()