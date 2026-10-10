"""Codebase tools — connect, index, search, read, write, patch, git.

The heavy lifting lives in backend/codebase.py (imported as cb).
This file exposes the tool wrappers the model sees and the connector
manifest for the sidebar.
"""
import os
import shutil
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path

from .registry import tool, connector
from vault import vault
from network import check_egress
import codebase as cb


WORKSPACE = Path(os.getenv("WORKSPACE_ROOT", "D:/Quill-Cowork/workspace")).resolve()
CLONES_DIR = WORKSPACE / "clones"
EXTRACTS_DIR = WORKSPACE / "codebases"

MAX_UNCOMPRESSED_BYTES = 500 * 1024 * 1024
MAX_ENTRIES = 10_000


@connector({
    "id": "codebase",
    "name": "Codebase",
    "description": "Connect to a codebase, read it, search it, edit it, push to git",
    "accent": "#059669",
    "widgets": [],
    "quick_actions": [
        {"label": "List codebases", "prompt": "List my connected codebases"},
    ],
})
class CodebaseConnector:
    pass


# Helpers

def _safe(name: str) -> str:
    return "".join(c for c in str(name) if c.isalnum() or c in "-_.").strip("-_.")


def _repo_name_from_url(url: str) -> str:
    base = url.rstrip("/").split("/")[-1]
    if base.endswith(".git"):
        base = base[:-4]
    return _safe(base) or "repo"


def _github_token() -> str:
    return (vault.get_safe("GITHUB_PERSONAL_ACCESS_TOKEN")
            or os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN", ""))


def _inject_token(url: str) -> str:
    """Embed a token in the URL for cloning a private repo over HTTPS.
    Only used during clone; the URL never persists in the git config
    because the repository is freshly created at the destination."""
    token = _github_token()
    if not token or not url.startswith("https://github.com/"):
        return url
    return url.replace("https://github.com/",
                       f"https://{token}@github.com/", 1)


def _is_within(base: Path, target: Path) -> bool:
    try:
        return target.resolve().is_relative_to(base.resolve())
    except Exception:
        return False


def _safe_extract_zip(zip_path: Path, dest: Path) -> str:
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        return f"not a valid zip file: {zip_path.name}"
    except Exception as e:
        return f"could not open zip: {e}"

    with zf:
        total_bytes = 0
        count = 0
        skipped = []

        for info in zf.infolist():
            name = info.filename

            if info.flag_bits & 0x1:
                return ("encrypted zip not supported — extract it manually "
                        "or remove the password")

            if name.endswith("/"):
                continue

            rel = Path(name)
            if rel.is_absolute() or ".." in rel.parts:
                skipped.append(f"{name} (unsafe path)")
                continue

            target = (dest / rel).resolve()
            if not _is_within(dest, target):
                skipped.append(f"{name} (escapes destination)")
                continue

            mode = (info.external_attr >> 16) & 0o170000
            if mode == 0o120000:
                skipped.append(f"{name} (symlink)")
                continue

            total_bytes += info.file_size
            if total_bytes > MAX_UNCOMPRESSED_BYTES:
                return (f"refused: uncompressed size exceeds "
                        f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB")
            count += 1
            if count > MAX_ENTRIES:
                return f"refused: more than {MAX_ENTRIES} files"

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out, length=64 * 1024)
            except Exception as e:
                skipped.append(f"{name} ({e})")

        msg = f"extracted {count} files"
        if skipped:
            msg += f"; skipped {len(skipped)}: " + "; ".join(skipped[:5])
            if len(skipped) > 5:
                msg += f" … (+{len(skipped) - 5} more)"
        return msg


def _safe_extract_tar(tar_path: Path, dest: Path) -> str:
    try:
        tf = tarfile.open(tar_path, mode="r:*")
    except tarfile.ReadError:
        return f"not a valid tar archive: {tar_path.name}"
    except Exception as e:
        return f"could not open tar: {e}"

    with tf:
        total_bytes = 0
        count = 0
        skipped = []

        for member in tf.getmembers():
            if member.isdir():
                continue
            if member.issym() or member.islnk():
                skipped.append(f"{member.name} (link)")
                continue

            rel = Path(member.name)
            if rel.is_absolute() or ".." in rel.parts:
                skipped.append(f"{member.name} (unsafe path)")
                continue

            target = (dest / rel).resolve()
            if not _is_within(dest, target):
                skipped.append(f"{member.name} (escapes destination)")
                continue

            total_bytes += member.size
            if total_bytes > MAX_UNCOMPRESSED_BYTES:
                return (f"refused: uncompressed size exceeds "
                        f"{MAX_UNCOMPRESSED_BYTES // (1024 * 1024)} MB")
            count += 1
            if count > MAX_ENTRIES:
                return f"refused: more than {MAX_ENTRIES} files"

            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                f = tf.extractfile(member)
                if f is None:
                    skipped.append(f"{member.name} (no data)")
                    continue
                with f, open(target, "wb") as out:
                    shutil.copyfileobj(f, out, length=64 * 1024)
            except Exception as e:
                skipped.append(f"{member.name} ({e})")

        msg = f"extracted {count} files"
        if skipped:
            msg += f"; skipped {len(skipped)}: " + "; ".join(skipped[:5])
            if len(skipped) > 5:
                msg += f" … (+{len(skipped) - 5} more)"
        return msg


def _flatten_single_root(dest: Path) -> Path:
    """If the archive contains one top-level folder (common for GitHub
    zip exports), descend into it so the tree isn't nested twice."""
    try:
        entries = [e for e in dest.iterdir() if e.name not in ("__MACOSX",)]
    except Exception:
        return dest
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return dest


# Lifecycle

@tool(destructive=True)
def connect_codebase(source: str, name: str = "") -> str:
    """Connect to a codebase: read it, index it, and make it searchable.
    source can be:
      - a local folder (e.g. D:/Projects/myapp)
      - a GitHub URL (will be cloned first)
      - a .zip / .tar / .tar.gz / .tgz archive (will be extracted)
    The user is prompted to approve before the codebase is read."""
    src = (source or "").strip()
    if not src:
        return "connect failed: no source provided"

    root_path = None

    # ---- GitHub URL ----
    if src.startswith("http://") or src.startswith("https://"):
        ok, reason = check_egress(src)
        if not ok:
            return f"blocked: {reason}"
        CLONES_DIR.mkdir(parents=True, exist_ok=True)
        repo_name = _safe(name) or _repo_name_from_url(src)
        dest = (CLONES_DIR / repo_name).resolve()
        if not _is_within(CLONES_DIR, dest):
            return "connect failed: bad clone path"
        if not dest.exists():
            try:
                r = subprocess.run(
                    ["git", "clone", "--depth", "1", _inject_token(src), str(dest)],
                    capture_output=True, text=True, timeout=180,
                )
            except subprocess.TimeoutExpired:
                return "connect failed: clone timeout"
            except FileNotFoundError:
                return "connect failed: git not found on PATH"
            if r.returncode != 0:
                from safety import redact_log
                err = redact_log((r.stderr or r.stdout).strip())[:300]
                return f"clone failed: {err}"
            # Clear any embedded token from the clone's remote URL so it
            # doesn't sit in .git/config at rest.
            try:
                subprocess.run(
                    ["git", "remote", "set-url", "origin", src],
                    cwd=dest, capture_output=True, text=True, timeout=10,
                )
            except Exception:
                pass
        root_path = dest

    # ---- Local archive or folder ----
    else:
        p = Path(src.lstrip("/\\")).expanduser().resolve()
        if not p.exists():
            return f"connect failed: path does not exist ({p})"

        lowered = p.name.lower()
        is_zip = lowered.endswith(".zip")
        is_tar = (lowered.endswith(".tar") or lowered.endswith(".tar.gz")
                  or lowered.endswith(".tgz") or lowered.endswith(".tar.bz2")
                  or lowered.endswith(".tar.xz"))

        if is_zip or is_tar:
            base_name = _safe(name) or _safe(p.stem.replace(".tar", ""))
            if not base_name:
                base_name = "codebase"
            dest = (EXTRACTS_DIR / base_name).resolve()
            if not _is_within(EXTRACTS_DIR, dest):
                return "connect failed: bad extract path"
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            dest.mkdir(parents=True, exist_ok=True)

            if is_zip:
                result = _safe_extract_zip(p, dest)
            else:
                result = _safe_extract_tar(p, dest)

            if result.startswith("refused") or result.startswith("not a valid"):
                return f"connect failed: {result}"

            root_path = _flatten_single_root(dest)

        elif p.is_dir():
            root_path = p

        else:
            return (f"connect failed: not a folder or supported archive "
                    f"(.zip, .tar, .tar.gz, .tgz) — got {p.suffix or 'no extension'}")

    if root_path is None:
        return "connect failed: could not resolve codebase root"

    # A2 fix: refuse to index hard-protected paths (.ssh, .aws, keychains,
    # browser profile dirs). These are never grantable via the AI.
    try:
        import grants as _grants
        refused = _grants.is_hard_refused(str(root_path))
        if refused:
            return (f"connect refused: {root_path} contains '{refused}' "
                    f"— this path is never indexable via the AI.")
    except Exception:
        pass

    try:
        meta = cb.ingest(root_path, name=name)
    except Exception as e:
        return f"connect failed: {e}"

    return (
        f"connected: {meta['name']}\n"
        f"root: {meta['root']}\n"
        f"files indexed: {meta['file_count']}\n"
        f"total bytes: {meta['total_bytes']:,}\n"
        f"elapsed: {meta['elapsed']}s\n\n"
        f"{cb.get_summary(meta['name'])}"
    )


@tool
def list_codebases() -> str:
    """List codebases the user has connected and indexed."""
    entries = cb.list_codebases()
    if not entries:
        return "no codebases connected yet"
    lines = []
    for e in entries:
        lines.append(
            f"- {e['name']}  ({e['file_count']} files, "
            f"{e['total_bytes']:,} bytes)  root: {e['root']}"
        )
    return "\n".join(lines)


@tool(destructive=True)
def disconnect_codebase(name: str) -> str:
    """Remove the index for a connected codebase. Does not delete the
    actual files — only the searchable index."""
    if cb.disconnect(name):
        return f"disconnected: {name}"
    return f"no codebase named '{name}'"


# Read / navigate

@tool
def codebase_info(name: str) -> str:
    """Show metadata, language mix, and file tree of a connected codebase."""
    meta = cb.get_meta(name)
    if not meta:
        return f"no codebase named '{name}'"
    header = (
        f"{meta['name']}\n"
        f"root: {meta['root']}\n"
        f"files: {meta['file_count']}\n"
        f"bytes: {meta['total_bytes']:,}\n"
    )
    return header + "\n" + cb.get_tree(name, max_lines=200)


@tool
def codebase_tree(name: str) -> str:
    """List all files in a connected codebase (paths only)."""
    return cb.get_tree(name, max_lines=500)


@tool
def codebase_search(name: str, query: str) -> str:
    """Keyword-search a connected codebase. Returns matching files with
    snippets, ranked by relevance. Use this before codebase_read to find
    the right file."""
    return cb.search(name, query)


@tool
def codebase_grep(name: str, pattern: str) -> str:
    """Regex search a connected codebase. Returns path:line matches."""
    return cb.grep(name, pattern)


@tool
def codebase_read(name: str, path: str) -> str:
    """Read a single file from a connected codebase."""
    return cb.read_file(name, path)


@tool(destructive=True)
def codebase_read_all(name: str) -> str:
    """Read the entire indexed codebase in a single call.
    Returns every file with path headers, up to ~200 KB.
    Use this when the user asks you to review, audit, analyze, or suggest
    changes to a codebase. Prefer this over calling codebase_read once per
    file — that wastes iterations."""
    return cb.read_all(name)


@tool
def codebase_symbols(name: str, kind: str = "all") -> str:
    """List symbols (functions, classes, interfaces, types) in a connected
    codebase. kind: 'function' | 'class' | 'interface' | 'type' | 'all'.
    Returns 'path:line  kind  name' for each symbol. Use this to find the
    shape of a codebase without reading every file."""
    return cb.symbols(name, kind=kind)


@tool
def codebase_find_symbol(name: str, symbol: str) -> str:
    """Find where a symbol (function, class, etc.) is defined. Returns
    'path:line  kind' for each definition. Use this before codebase_read
    to locate the right file."""
    return cb.find_symbol(name, symbol)


@tool
def codebase_imports(name: str, path: str, direction: str = "out") -> str:
    """Show imports for a file in a connected codebase.
    direction='out': what this file imports.
    direction='in': what other files import this one."""
    return cb.imports(name, path, direction=direction)


# Edit

@tool(destructive=True)
def codebase_write(name: str, path: str, content: str) -> str:
    """Write or overwrite a file inside a connected codebase.
    The user will be prompted to approve before the write."""
    return cb.write_file(name, path, content)


@tool(destructive=True)
def codebase_patch(name: str, path: str, find: str, replace: str,
                   count: int = 1) -> str:
    """Apply a targeted text replacement inside a file. Replace the first
    occurrence of `find` with `replace`. Set count to the total number of
    occurrences if you intend to replace all of them. Prefer this over
    codebase_write for small edits — it only needs the surrounding lines,
    not the whole file."""
    return cb.patch_file(name, path, find, replace, count=count)


# Git

def _write_askpass(token: str) -> str:
    """Write a short-lived askpass script OUTSIDE the repo so `git add -A`
    cannot stage it. Returns the path. Caller deletes it in a finally."""
    fd, path = tempfile.mkstemp(prefix="quill-askpass-", suffix=".cmd")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("@echo off\r\n")
        f.write(f"echo {token}\r\n")
    try:
        os.chmod(path, 0o600)
    except Exception:
        pass
    return path


def _git_push(name: str, remote: str, branch: str) -> str:
    meta = cb.get_meta(name)
    if not meta:
        return f"no codebase named '{name}'"
    root = Path(meta["root"])
    if not (root / ".git").exists():
        return "not a git repository"

    token = _github_token()
    env = os.environ.copy()
    askpass_path = None

    if token:
        askpass_path = _write_askpass(token)
        env["GIT_ASKPASS"] = askpass_path
        env["GIT_TERMINAL_PROMPT"] = "0"

    cmd = ["git", "push", remote]
    if branch:
        cmd.append(branch)

    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True,
                           timeout=120, env=env)
    except subprocess.TimeoutExpired:
        return "push failed: timeout"
    finally:
        if askpass_path:
            try:
                os.unlink(askpass_path)
            except Exception:
                pass

    if r.returncode != 0:
        return f"push failed: {(r.stdout + r.stderr).strip()[:400]}"
    return (r.stdout or r.stderr or "pushed").strip()[:400]


@tool(destructive=True)
def codebase_git(name: str, action: str, message: str = "",
                 branch: str = "") -> str:
    """Run a git operation on a connected codebase.
    action: 'status' | 'commit' | 'push'.
    For 'commit' provide a message. For 'push' optionally provide a branch.
    Push uses GITHUB_PERSONAL_ACCESS_TOKEN from the vault if available."""
    a = (action or "").strip().lower()
    if a == "status":
        return cb.git_status(name)
    if a == "commit":
        if not message:
            return "commit requires a message"
        return cb.git_commit(name, message)
    if a == "push":
        return _git_push(name, remote="origin", branch=branch)
    return f"unknown action: {action}"