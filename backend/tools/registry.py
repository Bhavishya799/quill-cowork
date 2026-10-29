import inspect
import json
from typing import Any, Callable, Dict, List, get_type_hints


_TYPE_MAP = {
    str: "string", int: "integer", float: "number", bool: "boolean",
    list: "array", dict: "object",
}


def _json_type(hint) -> str:
    origin = getattr(hint, "__origin__", None)
    if origin in (list, List):
        return "array"
    if origin in (dict, Dict):
        return "object"
    return _TYPE_MAP.get(hint, "string")


_tools: Dict[str, Dict[str, Any]] = {}
_connectors: Dict[str, Dict[str, Any]] = {}


def _derive_risk(destructive: bool, safety: dict | None) -> int:
    if safety:
        if safety.get("credential_access") or safety.get("network"):
            return 3
        if safety.get("writes_files") or safety.get("open_world"):
            return 2
        if safety.get("idempotent"):
            return 1
        if safety.get("read_only"):
            return 0
    return 2 if destructive else 0


def get_risk(name: str) -> int:
    return _tools.get(name, {}).get("risk", 2 if _tools.get(name, {}).get("destructive") else 0)


def get_safety(name: str) -> dict:
    return _tools.get(name, {}).get("safety", {})
_connectors: Dict[str, Dict[str, Any]] = {}


def tool(fn: Callable = None, *, destructive: bool = False,
         safety: dict | None = None):
    """
    safety: optional dict of {"read_only", "idempotent", "open_world",
    "writes_files", "network", "credential_access"} booleans.
    Risk level is derived: 0=read_only, 1=idempotent-write, 2=writes,
    3=network/credential/destructive. If safety is None, risk is
    inferred from `destructive` (False->0, True->2).
    """
    def wrap(f):
        sig = inspect.signature(f)
        hints = get_type_hints(f)
        doc = (f.__doc__ or "").strip().split("\n")[0]

        props, required = {}, []
        for name, param in sig.parameters.items():
            if name in ("self", "cls"):
                continue
            props[name] = {"type": _json_type(hints.get(name, str))}
            if param.default is inspect.Parameter.empty:
                required.append(name)

        risk = _derive_risk(destructive, safety)
        _tools[f.__name__] = {
            "function": f,
            "destructive": destructive,
            "risk": risk,
            "safety": safety or {},
            "schema": {
                "type": "function",
                "function": {
                    "name": f.__name__,
                    "description": doc or f.__name__,
                    "parameters": {
                        "type": "object",
                        "properties": props,
                        "required": required,
                    },
                },
            },
        }
        return f

    if fn is None:
        return wrap
    return wrap(fn)


def connector(manifest: Dict[str, Any]) -> Callable:
    def wrap(x):
        _connectors[manifest["id"]] = manifest
        return x
    return wrap


_mcp_server_for_tool: Dict[str, str] = {}


def register_external_tool(name: str, schema: Dict[str, Any],
                           caller, destructive: bool = True,
                           mcp_server: str = "") -> None:
    """Register a tool whose implementation lives outside this process."""
    _tools[name] = {
        "function": caller,
        "destructive": destructive,
        "schema": schema,
        "external": True,
    }
    if mcp_server:
        _mcp_server_for_tool[name] = mcp_server


def mcp_server_for(name: str) -> str:
    """Return the MCP server name for an mcp_* tool, or "" if unknown.
    Handles server names containing underscores correctly."""
    return _mcp_server_for_tool.get(name, "")


def unregister_external_tools(prefix: str) -> int:
    """Remove all tools whose name starts with prefix. Returns count."""
    names = [n for n in _tools if n.startswith(prefix)]
    for n in names:
        _tools.pop(n, None)
    return len(names)


def get_ollama_tools() -> List[Dict[str, Any]]:
    return [t["schema"] for t in _tools.values()]


def get_tool(name: str) -> Callable:
    if name not in _tools:
        raise KeyError(name)
    return _tools[name]["function"]


def is_destructive(name: str) -> bool:
    return _tools.get(name, {}).get("destructive", False)


def list_tools() -> List[str]:
    return list(_tools.keys())


def get_connectors() -> List[Dict[str, Any]]:
    return list(_connectors.values())


def call_tool_result(name: str, arguments: Dict[str, Any]):
    """Structured version of call_tool. Returns ToolResult."""
    from tool_result import succeeded, failed
    if name not in _tools:
        return failed(f"unknown tool: {name}")
    try:
        result = _tools[name]["function"](**(arguments or {}))
        if isinstance(result, (dict, list)):
            text = json.dumps(result, default=str)[:4000]
        else:
            text = str(result)[:4000]
        return succeeded(text)
    except Exception as e:
        return failed(f"tool error: {type(e).__name__}: {e}")


def call_tool(name: str, arguments: Dict[str, Any]) -> str:
    try:
        result = get_tool(name)(**arguments)
        if isinstance(result, (dict, list)):
            return json.dumps(result, default=str)[:4000]
        return str(result)[:4000]
    except Exception as e:
        return f"tool error: {type(e).__name__}: {e}"