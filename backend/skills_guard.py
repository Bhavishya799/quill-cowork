"""Skills security scanner + quarantine.

install_skill(src, name) copies to workspace/.quill/skills/.quarantine/<name>/,
scans, and only promotes to workspace/.quill/skills/<name>/ if clean.
"""
from __future__ import annotations
import ast
import base64
import json
import re
import shutil
import time
from pathlib import Path
from typing import Optional

from config import settings

SKILLS_ROOT = Path(settings.WORKSPACE_ROOT) / ".quill" / "skills"
QUARANTINE = SKILLS_ROOT / ".quarantine"
INSTALLED = SKILLS_ROOT / "installed"
for p in (SKILLS_ROOT, QUARANTINE, INSTALLED):
    p.mkdir(parents=True, exist_ok=True)

DANGEROUS_IMPORTS = {
    "subprocess", "ctypes", "socket", "http.client", "urllib",
    "requests", "httpx", "pty", "pickle", "multiprocessing",
    "concurrent.futures.process",
}
DANGEROUS_CALLS = {"eval", "exec", "compile", "__import__"}
DANGEROUS_ATTRS = {
    "os.system", "os.popen", "os.execv", "os.execvp",
    "os.spawnl", "os.spawnv", "os.fork",
}
_B64_RX = re.compile(r"[A-Za-z0-9+/]{120,}={0,2}")
_HEX_RX = re.compile(r"(?:\\x[0-9a-fA-F]{2}){8,}")


def _scan_ast(tree: ast.AST) -> list:
    findings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name in DANGEROUS_IMPORTS or a.name.split(".")[0] in DANGEROUS_IMPORTS:
                    findings.append({"line": getattr(node, "lineno", 0), "kind": "import", "target": a.name})
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod in DANGEROUS_IMPORTS or mod.split(".")[0] in DANGEROUS_IMPORTS:
                findings.append({"line": getattr(node, "lineno", 0), "kind": "import", "target": mod})
        elif isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Name) and fn.id in DANGEROUS_CALLS:
                findings.append({"line": getattr(node, "lineno", 0), "kind": "call", "target": fn.id})
            elif isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name):
                dotted = f"{fn.value.id}.{fn.attr}"
                if dotted in DANGEROUS_ATTRS:
                    findings.append({"line": getattr(node, "lineno", 0), "kind": "call", "target": dotted})
    return findings


def scan_file(path: Path) -> dict:
    findings = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "findings": [{"kind": "read_error", "error": str(e)}]}
    if path.suffix == ".py":
        try:
            tree = ast.parse(text)
            findings.extend(_scan_ast(tree))
        except SyntaxError as e:
            findings.append({"line": e.lineno or 0, "kind": "syntax_error", "target": str(e)})
    for m in _B64_RX.finditer(text):
        findings.append({"line": text[:m.start()].count("\n") + 1, "kind": "b64_blob", "length": len(m.group(0))})
    for m in _HEX_RX.finditer(text):
        findings.append({"line": text[:m.start()].count("\n") + 1, "kind": "hex_blob"})
    return {"ok": not findings, "findings": findings}


def scan_dir(root: Path) -> dict:
    results = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in (".py", ".md", ".sh", ".ps1"):
            r = scan_file(p)
            results.append({"path": str(p.relative_to(root)), **r})
    overall_ok = all(r["ok"] for r in results)
    return {"ok": overall_ok, "files": results}


def install_skill(src: Path, name: str) -> dict:
    name = "".join(c for c in name if c.isalnum() or c in "-_").strip("-_")
    if not name:
        return {"ok": False, "error": "invalid name"}
    if not src.is_dir():
        return {"ok": False, "error": "source is not a directory"}
    qdest = QUARANTINE / name
    if qdest.exists():
        shutil.rmtree(qdest)
    shutil.copytree(src, qdest)
    scan = scan_dir(qdest)
    if not scan["ok"]:
        return {"ok": False, "quarantined": str(qdest), "scan": scan}
    idest = INSTALLED / name
    if idest.exists():
        shutil.rmtree(idest)
    shutil.move(str(qdest), str(idest))
    return {"ok": True, "installed": str(idest), "scan": scan}


def list_skills() -> dict:
    def _list(p: Path):
        return sorted(d.name for d in p.iterdir() if d.is_dir()) if p.exists() else []
    return {"installed": _list(INSTALLED), "quarantined": _list(QUARANTINE)}
