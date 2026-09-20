"""Onyx tool registry — decorator-based."""

import inspect
import json
from typing import Any, Callable, Dict, List, get_type_hints


_REGISTRY: Dict[str, Dict[str, Any]] = {}
_CONNECTORS: Dict[str, Dict[str, Any]] = {}


def _python_type_to_json(tp) -> str:
    if tp is str:
        return "string"
    if tp is int:
        return "integer"
    if tp is float:
        return "number"
    if tp is bool:
        return "boolean"
    if tp is list or tp is List:
        return "array"
    if tp is dict or tp is Dict:
        return "object"
    return "string"


def tool(fn: Callable) -> Callable:
    """Decorator: register a function as an agent tool."""
    name = fn.__name__
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)
    doc = (fn.__doc__ or "").strip()

    properties = {}
    required = []

    for param_name, param in sig.parameters.items():
        if param_name in ("self", "cls"):
            continue
        ptype = hints.get(param_name, str)
        properties[param_name] = {"type": _python_type_to_json(ptype)}
        if param.default is inspect.Parameter.empty:
            required.append(param_name)

    _REGISTRY[name] = {
        "function": fn,
        "schema": {
            "type": "function",
            "function": {
                "name": name,
                "description": doc.split("\n")[0] if doc else name,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        },
    }
    return fn


def connector(manifest: Dict[str, Any]) -> Callable:
    """Decorator: register a connector manifest for the reactive UI."""
    def wrapper(fn_or_cls):
        _CONNECTORS[manifest["id"]] = manifest
        return fn_or_cls
    return wrapper


def get_ollama_tools() -> List[Dict[str, Any]]:
    return [entry["schema"] for entry in _REGISTRY.values()]


def get_tool(name: str) -> Callable:
    entry = _REGISTRY.get(name)
    if not entry:
        raise KeyError(f"Tool '{name}' not registered")
    return entry["function"]


def list_tools() -> List[str]:
    return list(_REGISTRY.keys())


def get_connectors() -> List[Dict[str, Any]]:
    return list(_CONNECTORS.values())


def call_tool(name: str, arguments: Dict[str, Any]) -> str:
    try:
        fn = get_tool(name)
        result = fn(**arguments)
        if isinstance(result, (dict, list)):
            return json.dumps(result, indent=2, default=str)[:4000]
        return str(result)[:4000]
    except Exception as e:
        return f"Error calling {name}: {type(e).__name__}: {e}"