"""Code parsing.

Python uses the stdlib ast module. JS/TS falls back to regex because a
tree-sitter dependency is heavier than the value it would add here.
"""
import ast as _ast
import re
from typing import Dict, List


def extract_python_symbols(content: str) -> List[Dict]:
    """Parse Python source. Returns function and class definitions.

    Uses ast.walk, so nested functions and methods are included, matching
    the behavior of the original codebase.extract_symbols.
    """
    out: List[Dict] = []
    try:
        tree = _ast.parse(content)
    except (SyntaxError, ValueError, TypeError):
        return out
    for node in _ast.walk(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            out.append({"name": node.name, "kind": "function",
                        "line": getattr(node, "lineno", 0)})
        elif isinstance(node, _ast.ClassDef):
            out.append({"name": node.name, "kind": "class",
                        "line": getattr(node, "lineno", 0)})
    return out


def extract_python_imports(content: str) -> List[str]:
    """Parse Python imports via ast. Returns module names.

    Walks the whole AST. Imports inside functions are included. Relative
    imports (from . import x) have no module name and are skipped.
    """
    try:
        tree = _ast.parse(content)
    except (SyntaxError, ValueError, TypeError):
        return []
    mods: List[str] = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.Import):
            for alias in node.names:
                mods.append(alias.name)
        elif isinstance(node, _ast.ImportFrom):
            if node.module:
                mods.append(node.module)
    return mods


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


def extract_js_symbols(content: str) -> List[Dict]:
    """Regex-based JS/TS symbol extraction."""
    out: List[Dict] = []
    for rx, kind in [(_JS_FN, "function"), (_JS_CLASS, "class"),
                     (_JS_INTERFACE, "interface"), (_JS_TYPE, "type")]:
        for m in rx.finditer(content):
            line = content[:m.start()].count("\n") + 1
            out.append({"name": m.group(1), "kind": kind, "line": line})
    for m in _JS_ARROW.finditer(content):
        line = content[:m.start()].count("\n") + 1
        out.append({"name": m.group(1), "kind": "function", "line": line})
    return out
