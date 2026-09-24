"""Codebase ingestion and retrieval.

Reads the entire codebase at connect time (chunk by chunk: one file per
record), writes a searchable index to workspace/.quill/codebases/<name>/,
and exposes query primitives the model uses at run time.
"""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Optional

from vault import vault


WORKSPACE = Path(os.getenv("WORKSPACE_ROOT", "D:/Quill-Cowork/workspace")).resolve()
INDEX_ROOT = WORKSPACE / ".quill" / "codebases"

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__",
    "dist", "build", ".next", ".nuxt", "target", "vendor",
    ".idea", ".vscode", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "coverage", "htmlcov", ".tox", ".eggs",
}

SKIP_EXT = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico",
    ".pdf", ".zip", ".tar", ".gz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a",
    ".pyc", ".pyo", ".class", ".jar", ".war",
    ".mp3", ".mp4", ".mov", ".avi", ".webm", ".wav", ".flac",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
}

LANG_BY_EXT = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".jsx": "jsx", ".tsx": "tsx", ".java": "java", ".go": "go",
    ".rs": "rust", ".rb": "ruby", ".php": "php", ".c": "c",
    ".cpp": "cpp", ".h": "c", ".hpp": "cpp", ".cs": "csharp",
    ".kt": "kotlin", ".swift": "swift", ".m": "objc",
    ".html": "html", ".css": "css", ".scss": "scss", ".sass": "sass",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".md": "markdown", ".rst": "rst", ".txt": "text",
    ".sh": "shell", ".bash": "bash", ".zsh": "zsh", ".ps1": "powershell",
    ".sql": "sql", ".graphql": "graphql", ".proto": "protobuf",
    ".ini": "ini", ".cfg": "ini",
}

MAX_FILE_BYTES = 200_000
MAX_TOTAL_FILES = 3000
MAX_TOTAL_BYTES = 30_000_000

KEY_FILES = [
    "README.md", "README.rst", "README.txt", "readme.md",
    "package.json", "pyproject.toml", "requirements.txt",
    "setup.py", "Cargo.toml", "go.mod", "pom.xml",
    "Makefile", "Dockerfile", "docker-compose.yml",
    ".env.example", "tsconfig.json",
]


def safe_name(name: str) -> str:
    return "".join(c for c in str(name) if c.isalnum() or c in "-_.").strip("-_.")


def index_dir(name: str) -> Path:
    return INDEX_ROOT / safe_name(name)


def _is_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:8000]
    except Exception:
        return True
    if b"\x00" in chunk:
        return True
    if not chunk:
        return False
    printable = sum(1 for b in chunk if 32 <= b < 127 or b in (9, 10, 13))
    return printable / len(chunk) < 0.85


def _lang_for(path: Path) -> str:
    return LANG_BY_EXT.get(path.suffix.lower(), "")


def _should_skip_dir(name: str) -> bool:
    return name in SKIP_DIRS or name.startswith(".")


def _should_skip_file(path: Path) -> bool:
    if path.suffix.lower() in SKIP_EXT:
        return True
    if path.name in {".DS_Store", "Thumbs.db"}:
        return True
    if path.name.endswith(".min.js") or path.name.endswith(".min.css"):
        return True
    return False


def _walk(root: Path) -> List[Path]:
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        for f in filenames:
            p = Path(dirpath) / f
            if not _should_skip_file(p):
                out.append(p)
    return out


def ingest(root: Path, name: str = "") -> Dict:
    root = root.resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"not a directory: {root}")

    cb_name = safe_name(name) or root.name
    idx = index_dir(cb_name)
    if idx.exists():
        shutil.rmtree(idx)
    idx.mkdir(parents=True, exist_ok=True)

    started = time.time()
    all_files = _walk(root)

    records = []
    total_bytes = 0
    skipped_binary = skipped_large = skipped_cap = 0

    for p in all_files:
        if len(records) >= MAX_TOTAL_FILES:
            skipped_cap += 1
            continue
        try:
            size = p.stat().st_size
        except Exception:
            continue
        if size > MAX_FILE_BYTES:
            skipped_large += 1
            continue
        if total_bytes + size > MAX_TOTAL_BYTES:
            skipped_cap += 1
            continue
        if _is_binary(p):
            skipped_binary += 1
            continue
        try:
            content = p.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        rel = str(p.relative_to(root))
        records.append({
            "path": rel,
            "size": size,
            "lang": _lang_for(p),
            "lines": content.count("\n") + 1,
            "content": content,
        })
        total_bytes += size

    with (idx / "files.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")

    tree_paths = sorted(r["path"] for r in records)
    (idx / "tree.txt").write_text("\n".join(tree_paths), encoding="utf-8")

    key_excerpts = []
    for kf in KEY_FILES:
        for rec in records:
            if rec["path"].lower() == kf.lower() or rec["path"].endswith("/" + kf):
                excerpt = rec["content"][:1200]
                key_excerpts.append(f"### {rec['path']}\n```\n{excerpt}\n```")
                break

    meta = {
        "name": cb_name,
        "root": str(root),
        "connected_at": time.time(),
        "file_count": len(records),
        "total_bytes": total_bytes,
        "skipped_binary": skipped_binary,
        "skipped_large": skipped_large,
        "skipped_cap": skipped_cap,
        "elapsed": round(time.time() - started, 2),
    }
    (idx / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    (idx / "summary.md").write_text(
        _build_summary(meta, records, key_excerpts), encoding="utf-8"
    )
    return meta


def _build_summary(meta: Dict, records: List[Dict], key_excerpts: List[str]) -> str:
    lines = []
    lines.append(f"# Codebase: {meta['name']}")
    lines.append(f"Root: {meta['root']}")
    lines.append(f"Indexed files: {meta['file_count']}")
    lines.append(f"Total bytes: {meta['total_bytes']:,}")
    if meta.get("skipped_binary"):
        lines.append(f"Skipped binary: {meta['skipped_binary']}")
    if meta.get("skipped_large"):
        lines.append(f"Skipped >200KB: {meta['skipped_large']}")

    langs: Dict[str, int] = {}
    for r in records:
        langs[r["lang"] or "other"] = langs.get(r["lang"] or "other", 0) + 1
    top = sorted(langs.items(), key=lambda x: -x[1])[:8]
    lines.append("")
    lines.append("Languages:")
    for lang, count in top:
        lines.append(f"- {lang}: {count}")

    lines.append("")
    lines.append(f"File tree (first 100 of {len(records)}):")
    for r in sorted(records, key=lambda x: x["path"])[:100]:
        lines.append(f"- {r['path']}")
    if len(records) > 100:
        lines.append(f"… ({len(records) - 100} more, use codebase_tree to see all)")

    if key_excerpts:
        lines.append("")
        lines.append("Key files:")
        lines.append("\n\n".join(key_excerpts))

    text = "\n".join(lines)
    if len(text) > 3500:
        text = text[:3500] + "\n… [truncated]"
    return text


def list_codebases() -> List[Dict]:
    if not INDEX_ROOT.exists():
        return []
    out = []
    for d in sorted(INDEX_ROOT.iterdir()):
        if not d.is_dir():
            continue
        mf = d / "meta.json"
        if not mf.exists():
            continue
        try:
            out.append(json.loads(mf.read_text(encoding="utf-8")))
        except Exception:
            continue
    return out


def get_meta(name: str) -> Optional[Dict]:
    mf = index_dir(name) / "meta.json"
    if not mf.exists():
        return None
    try:
        return json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        return None


def disconnect(name: str) -> bool:
    idx = index_dir(name)
    if idx.exists():
        shutil.rmtree(idx)
        return True
    return False


def get_summary(name: str, max_chars: int = 3500) -> str:
    f = index_dir(name) / "summary.md"
    if not f.exists():
        return f"no index for '{name}'"
    return f.read_text(encoding="utf-8")[:max_chars]


def get_tree(name: str, max_lines: int = 400) -> str:
    f = index_dir(name) / "tree.txt"
    if not f.exists():
        return f"no index for '{name}'"
    lines = f.read_text(encoding="utf-8").splitlines()
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines]) + f"\n… ({len(lines) - max_lines} more)"
    return "\n".join(lines)


def search(name: str, query: str, limit: int = 15) -> str:
    files = index_dir(name) / "files.jsonl"
    if not files.exists():
        return f"no index for '{name}'"
    q = query.lower().strip()
    if not q:
        return "empty query"
    terms = [t for t in re.split(r"\s+", q) if len(t) >= 2]

    results = []
    with files.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            cl = rec["content"].lower()
            pl = rec["path"].lower()
            score = 0
            hits = []
            for term in terms:
                if term in pl:
                    score += 10
                cnt = cl.count(term)
                if cnt:
                    score += min(cnt, 5)
                    i = cl.find(term)
                    start = max(0, i - 60)
                    end = min(len(rec["content"]), i + 140)
                    hits.append(rec["content"][start:end].replace("\n", " "))
            if score:
                results.append((score, rec["path"], hits[:2]))

    results.sort(key=lambda x: -x[0])
    if not results:
        return f"no matches for '{query}'"
    lines = []
    for score, path, hits in results[:limit]:
        lines.append(f"[{score}] {path}")
        for h in hits:
            lines.append(f"    …{h}…")
    return "\n".join(lines)


def grep(name: str, pattern: str, limit: int = 40) -> str:
    files = index_dir(name) / "files.jsonl"
    if not files.exists():
        return f"no index for '{name}'"
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return f"bad regex: {e}"
    out = []
    with files.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            for i, ln in enumerate(rec["content"].splitlines(), 1):
                if rx.search(ln):
                    out.append(f"{rec['path']}:{i}: {ln.strip()[:140]}")
                    if len(out) >= limit:
                        break
            if len(out) >= limit:
                break
    return "\n".join(out) if out else f"no matches for /{pattern}/"


def read_file(name: str, path: str, max_chars: int = 8000) -> str:
    files = index_dir(name) / "files.jsonl"
    want = path.strip().lstrip("/\\")
    if files.exists():
        with files.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                if rec["path"] == want:
                    c = rec["content"]
                    if len(c) > max_chars:
                        return c[:max_chars] + f"\n… (truncated, {len(c)} chars total)"
                    return c
    meta = get_meta(name)
    if meta:
        disk = Path(meta["root"]) / want
        if disk.is_file():
            try:
                return disk.read_text(encoding="utf-8", errors="replace")[:max_chars]
            except Exception as e:
                return f"read failed: {e}"
    return f"file not found in index: {path}"


def write_file(name: str, path: str, content: str) -> str:
    meta = get_meta(name)
    if not meta:
        return f"no codebase named '{name}'"
    root = Path(meta["root"]).resolve()
    rel = path.strip().lstrip("/\\")
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        return f"refused: {path} escapes codebase root"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _update_index_file(name, rel, content)
    return f"wrote {len(content)} chars to {rel}"


def _update_index_file(name: str, rel: str, content: str) -> None:
    files = index_dir(name) / "files.jsonl"
    if not files.exists():
        return
    records = []
    found = False
    with files.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec["path"] == rel:
                rec["content"] = content
                rec["size"] = len(content.encode("utf-8"))
                rec["lines"] = content.count("\n") + 1
                found = True
            records.append(rec)
    if not found:
        records.append({
            "path": rel,
            "size": len(content.encode("utf-8")),
            "lang": _lang_for(Path(rel)),
            "lines": content.count("\n") + 1,
            "content": content,
        })
    with files.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")


def git_status(name: str) -> str:
    meta = get_meta(name)
    if not meta:
        return f"no codebase named '{name}'"
    root = Path(meta["root"])
    if not (root / ".git").exists():
        return "not a git repository"
    try:
        r = subprocess.run(["git", "status", "--short", "--branch"],
                            cwd=root, capture_output=True, text=True, timeout=15)
        return (r.stdout or "(clean)").strip()
    except Exception as e:
        return f"git status failed: {e}"


def git_commit(name: str, message: str) -> str:
    meta = get_meta(name)
    if not meta:
        return f"no codebase named '{name}'"
    root = Path(meta["root"])
    if not (root / ".git").exists():
        return "not a git repository"
    try:
        subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True, timeout=30)
        r = subprocess.run(["git", "commit", "-m", message],
                            cwd=root, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return f"commit failed: {(r.stdout + r.stderr).strip()[:300]}"
        return (r.stdout or "committed").strip()[:400]
    except Exception as e:
        return f"git commit failed: {e}"


def git_push(name: str, remote: str = "origin", branch: str = "") -> str:
    meta = get_meta(name)
    if not meta:
        return f"no codebase named '{name}'"
    root = Path(meta["root"])
    if not (root / ".git").exists():
        return "not a git repository"

    token = vault.get_safe("GITHUB_PERSONAL_ACCESS_TOKEN")
    if token:
        try:
            r = subprocess.run(["git", "remote", "get-url", remote],
                                cwd=root, capture_output=True, text=True, timeout=10)
            url = (r.stdout or "").strip()
            if "github.com" in url and "@" not in url.split("github.com")[0]:
                new_url = url.replace("https://github.com/",
                                       f"https://{token}@github.com/", 1)
                subprocess.run(["git", "remote", "set-url", remote, new_url],
                                cwd=root, capture_output=True, timeout=10)
        except Exception:
            pass

    cmd = ["git", "push", remote]
    if branch:
        cmd.append(branch)
    try:
        r = subprocess.run(cmd, cwd=root, capture_output=True, text=True, timeout=120)
        if r.returncode != 0:
            return f"push failed: {(r.stdout + r.stderr).strip()[:400]}"
        return (r.stdout or r.stderr or "pushed").strip()[:400]
    except Exception as e:
        return f"git push failed: {e}"
        

# =====================================================================
# Phase One: symbols, imports, patch
# =====================================================================

_PY_FN = None  # populated lazily to avoid importing ast at module load


def _extract_symbols_python(content: str):
    global _PY_FN
    if _PY_FN is None:
        import ast as _ast
        _PY_FN = _ast
    ast = _PY_FN
    out = []
    try:
        tree = ast.parse(content)
    except Exception:
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append({"name": node.name, "kind": "function",
                        "line": getattr(node, "lineno", 0)})
        elif isinstance(node, ast.ClassDef):
            out.append({"name": node.name, "kind": "class",
                        "line": getattr(node, "lineno", 0)})
    return out


_JS_FN = re.compile(
    r"^\s*(?:export\s+)?(?:async\s+)?function\s+([A-Za-z_$][\w$]*)",
    re.MULTILINE)
_JS_ARROW = re.compile(
    r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(",
    re.MULTILINE)
_JS_CLASS = re.compile(
    r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)", re.MULTILINE)
_JS_INTERFACE = re.compile(
    r"^\s*(?:export\s+)?interface\s+([A-Za-z_$][\w$]*)", re.MULTILINE)
_JS_TYPE = re.compile(
    r"^\s*(?:export\s+)?type\s+([A-Za-z_$][\w$]*)\s*=", re.MULTILINE)


def _extract_symbols_js(content: str):
    out = []
    for rx, kind in [(_JS_FN, "function"), (_JS_CLASS, "class"),
                     (_JS_INTERFACE, "interface"), (_JS_TYPE, "type")]:
        for m in rx.finditer(content):
            line = content[:m.start()].count("\n") + 1
            out.append({"name": m.group(1), "kind": kind, "line": line})
    for m in _JS_ARROW.finditer(content):
        line = content[:m.start()].count("\n") + 1
        out.append({"name": m.group(1), "kind": "function", "line": line})
    return out


def _extract_symbols(path: str, content: str):
    ext = Path(path).suffix.lower()
    if ext == ".py":
        return _extract_symbols_python(content)
    if ext in (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"):
        return _extract_symbols_js(content)
    return []


def symbols(name: str, kind: str = "all", limit: int = 400) -> str:
    files = index_dir(name) / "files.jsonl"
    if not files.exists():
        return f"no index for '{name}'"
    want = (kind or "all").lower()
    rows = []
    with files.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            for s in _extract_symbols(rec["path"], rec.get("content", "")):
                if want != "all" and s["kind"] != want:
                    continue
                rows.append((rec["path"], s["kind"], s["name"], s["line"]))
    if not rows:
        return f"no symbols found in '{name}'"
    rows.sort(key=lambda r: (r[0], r[3]))
    out = [f"{p}:{ln}  {k}  {n}" for (p, k, n, ln) in rows[:limit]]
    if len(rows) > limit:
        out.append(f"… ({len(rows) - limit} more)")
    return "\n".join(out)


def find_symbol(name: str, symbol: str) -> str:
    files = index_dir(name) / "files.jsonl"
    if not files.exists():
        return f"no index for '{name}'"
    sym = symbol.strip()
    if not sym:
        return "empty symbol"
    matches = []
    rx = re.compile(r"^\s*(?:export\s+)?(?:async\s+)?"
                    r"(?:function|class|interface|type|const|let|var|def)\s+"
                    + re.escape(sym) + r"\b")
    with files.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            for s in _extract_symbols(rec["path"], rec.get("content", "")):
                if s["name"] == sym:
                    matches.append(f"{rec['path']}:{s['line']}  {s['kind']}")
                    break
            if not matches:
                for i, ln in enumerate(rec.get("content", "").splitlines(), 1):
                    if rx.search(ln):
                        matches.append(f"{rec['path']}:{i}  (source)")
                        break
    if not matches:
        return f"symbol not found: {sym}"
    return "\n".join(matches[:20])


_PY_IMPORT_FROM = re.compile(
    r"^\s*from\s+([\w\.]+)\s+import\s+", re.MULTILINE)
_PY_IMPORT_PLAIN = re.compile(
    r"^\s*import\s+([\w\.]+)", re.MULTILINE)
_JS_IMPORT = re.compile(
    r"""(?:^|\n)\s*(?:import\s+(?:[^'"]+\s+from\s+)?|require\s*\(\s*)['"]([^'"]+)['"]""",
    re.MULTILINE)


def _imports_of(path: str, content: str):
    ext = Path(path).suffix.lower()
    mods = []
    if ext == ".py":
        for m in _PY_IMPORT_FROM.finditer(content):
            mods.append(m.group(1))
        for m in _PY_IMPORT_PLAIN.finditer(content):
            mods.append(m.group(1))
    elif ext in (".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs"):
        for m in _JS_IMPORT.finditer(content):
            mods.append(m.group(1))
    return mods


def imports(name: str, path: str, direction: str = "out") -> str:
    files = index_dir(name) / "files.jsonl"
    if not files.exists():
        return f"no index for '{name}'"
    want = path.strip().lstrip("/\\")
    direction = (direction or "out").lower()

    records = []
    with files.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                records.append(json.loads(line))
            except Exception:
                continue

    if direction == "out":
        for rec in records:
            if rec["path"] == want:
                mods = _imports_of(rec["path"], rec.get("content", ""))
                if not mods:
                    return f"{want} imports nothing"
                return "\n".join(f"- {m}" for m in mods)
        return f"file not found in index: {path}"

    if direction == "in":
        hit = []
        needle_variants = set()
        base = Path(want).stem
        needle_variants.add(base)
        needle_variants.add(want.replace("\\", "/").replace("/", "."))
        for rec in records:
            if rec["path"] == want:
                continue
            for mod in _imports_of(rec["path"], rec.get("content", "")):
                tail = mod.split(".")[-1].split("/")[-1]
                if tail in needle_variants or mod in needle_variants:
                    hit.append(f"{rec['path']}  → {mod}")
                    break
        if not hit:
            return f"nothing imports {want}"
        return "\n".join(hit[:50])

    return f"unknown direction: {direction}"


def patch_file(name: str, path: str, find: str, replace: str,
               count: int = 1) -> str:
    meta = get_meta(name)
    if not meta:
        return f"no codebase named '{name}'"
    root = Path(meta["root"]).resolve()
    rel = path.strip().lstrip("/\\")
    target = (root / rel).resolve()
    if not target.is_relative_to(root):
        return f"refused: {path} escapes codebase root"
    if not target.is_file():
        return f"not found: {rel}"

    original = target.read_text(encoding="utf-8", errors="replace")
    if find == "":
        return "find string is empty"
    if find not in original:
        return f"find string not present in {rel}"

    occurrences = original.count(find)
    if occurrences > 1 and count == 1:
        return (f"find string appears {occurrences} times in {rel}; pass "
                f"count={occurrences} to replace all, or use a more specific find")

    replace_n = occurrences if count <= 0 else min(count, occurrences)
    new_content = original.replace(find, replace, replace_n)
    if new_content == original:
        return "no change made"

    target.write_text(new_content, encoding="utf-8")
    _update_index_file(name, rel, new_content)
    return f"patched {rel}: replaced {replace_n} occurrence(s)"