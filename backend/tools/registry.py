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


def tool(fn: Callable = None, *, destructive: bool = False):
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

        _tools[f.__name__] = {
            "function": f,
            "destructive": destructive,
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


def call_tool(name: str, arguments: Dict[str, Any]) -> str:
    try:
        result = get_tool(name)(**arguments)
        if isinstance(result, (dict, list)):
            return json.dumps(result, default=str)[:4000]
        return str(result)[:4000]
    except Exception as e:
        return f"tool error: {type(e).__name__}: {e}"