"""MCP client manager.

Connects to Model Context Protocol servers declared in mcp_servers.json,
discovers their tools, registers them into Quill's tool registry under
the name mcp_<server>_<tool>, and routes calls back to the right server.

Runs in a dedicated background thread with its own asyncio event loop so
the sync call_tool() path (invoked via asyncio.to_thread) can call into
async MCP sessions without changing the rest of the agent.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional

CONFIG_PATH = Path(__file__).parent / "mcp_servers.json"

# Cap on how long a single MCP tool call can take.
TOOL_CALL_TIMEOUT = 120.0


def _resolve_env_value(value: str) -> str:
    """Replace ${VAR} with os.environ[VAR] or the vault."""
    if not isinstance(value, str) or "${" not in value:
        return value
    def sub(m):
        var = m.group(1)
        env_v = os.environ.get(var)
        if env_v:
            return env_v
        try:
            from vault import vault
            v = vault.get_safe(var)
            if v:
                return v
        except Exception:
            pass
        return ""
    return re.sub(r"\$\{([A-Z_][A-Z0-9_]*)\}", sub, value)




def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {"mcpServers": {}}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[mcp] config parse error: {e}")
        return {"mcpServers": {}}
    if not isinstance(data, dict):
        return {"mcpServers": {}}
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        servers = {}
    return {"mcpServers": servers}


def _mcp_tool_to_ollama_schema(server: str, tool) -> dict:
    """Convert an MCP tool definition into an Ollama tool schema."""
    name = getattr(tool, "name", None) or "unnamed"
    description = getattr(tool, "description", "") or name
    input_schema = getattr(tool, "inputSchema", None) or {}
    if not isinstance(input_schema, dict):
        input_schema = {}
    params = {
        "type": "object",
        "properties": input_schema.get("properties", {}) or {},
        "required": input_schema.get("required", []) or [],
    }
    return {
        "type": "function",
        "function": {
            "name": f"mcp_{server}_{name}",
            "description": f"[MCP:{server}] {description}",
            "parameters": params,
        },
    }


class MCPManager:
    def __init__(self):
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stack: Optional[AsyncExitStack] = None
        self._clients: Dict[str, Any] = {}          # server -> Client
        self._tool_map: Dict[str, tuple] = {}       # prefixed -> (server, original)
        self._schemas: Dict[str, dict] = {}         # prefixed -> ollama schema
        self._destructive: Dict[str, bool] = {}     # prefixed -> bool
        self._errors: Dict[str, str] = {}           # server -> error
        self._ready = threading.Event()
        self._running = False

    # -------- public API --------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="mcp-loop"
        )
        self._thread.start()
        if not self._ready.wait(timeout=30):
            print("[mcp] startup timed out")

    def stop(self) -> None:
        if not self._running:
            return
        if self._loop and self._stack:
            fut = asyncio.run_coroutine_threadsafe(
                self._stack.aclose(), self._loop
            )
            try:
                fut.result(timeout=10)
            except Exception:
                pass
        if self._loop:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread:
            self._thread.join(timeout=5)
        self._running = False

    def get_schemas(self) -> List[dict]:
        return list(self._schemas.values())

    def get_destructive(self, prefixed_name: str) -> bool:
        return self._destructive.get(prefixed_name, True)

    def get_server_for(self, prefixed_name: str) -> str:
        """Return the server name for a given mcp_<server>_<tool> tool."""
        entry = self._tool_map.get(prefixed_name)
        return entry[0] if entry else ""


    def call_tool_sync(self, prefixed_name: str, args: dict) -> str:
        entry = self._tool_map.get(prefixed_name)
        if entry is None:
            return f"mcp error: unknown tool {prefixed_name}"
        server, original = entry
        client = self._clients.get(server)
        if client is None:
            return f"mcp error: server {server} not connected"

        if not self._loop:
            return "mcp error: event loop not running"

        fut = asyncio.run_coroutine_threadsafe(
            self._async_call(client, original, args), self._loop
        )
        try:
            return fut.result(timeout=TOOL_CALL_TIMEOUT)
        except asyncio.TimeoutError:
            return f"mcp error: {prefixed_name} timed out"
        except Exception as e:
            return f"mcp error: {type(e).__name__}: {e}"

    def status(self) -> dict:
        return {
            "running": self._running,
            "servers": {
                name: {
                    "connected": name in self._clients,
                    "tool_count": sum(
                        1 for p in self._tool_map if p.startswith(f"mcp_{name}_")
                    ),
                    "error": self._errors.get(name, ""),
                }
                for name in self._known_servers()
            },
            "tool_count": len(self._tool_map),
        }

    # -------- internals --------

    def _known_servers(self) -> List[str]:
        servers = set(self._clients.keys())
        servers.update(self._errors.keys())
        return sorted(servers)

    def _run_loop(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_start())
        except Exception as e:
            print(f"[mcp] start failed: {type(e).__name__}: {e}")
            self._ready.set()
            return
        self._ready.set()
        try:
            self._loop.run_forever()
        except Exception:
            pass

    async def _async_start(self) -> None:
        cfg = _load_config()
        servers = cfg.get("mcpServers") or {}
        if not servers:
            print("[mcp] no servers configured")
            return

        self._stack = AsyncExitStack()
        await self._stack.__aenter__()

        # Import lazily so a missing mcp package doesn't break startup
        try:
            from mcp import Client, StdioServerParameters  # type: ignore
            from mcp.client.stdio import stdio_client  # type: ignore
        except ImportError as e:
            print(f"[mcp] SDK not installed: {e}")
            return

        for name, spec in servers.items():
            if not isinstance(spec, dict):
                continue
            try:
                client = await self._connect_one(
                    name, spec, Client, StdioServerParameters, stdio_client
                )
                if client is None:
                    continue
                self._clients[name] = client
                await self._discover_tools(name, client)
            except Exception as e:
                self._errors[name] = f"{type(e).__name__}: {e}"
                print(f"[mcp] {name}: {self._errors[name]}")

    async def _connect_one(self, name, spec, Client, StdioServerParameters,
                           stdio_client):
        # HTTP/SSE transport
        url = spec.get("url")
        if url:
            transport_type = (spec.get("transport") or "http").lower()
            if transport_type in ("http", "streamable-http", "streamable_http"):
                try:
                    from mcp.client.streamable_http import (  # type: ignore
                        streamablehttp_client,
                    )
                except ImportError:
                    self._errors[name] = "streamable HTTP transport unavailable"
                    return None
                transport = streamablehttp_client(url)
            else:
                # SSE fallback
                try:
                    from mcp.client.sse import sse_client  # type: ignore
                except ImportError:
                    self._errors[name] = "SSE transport unavailable"
                    return None
                transport = sse_client(url)
            client = await self._stack.enter_async_context(Client(transport))
            print(f"[mcp] {name}: connected over {transport_type}")
            return client

        # stdio transport
        command = spec.get("command")
        if not command:
            self._errors[name] = "no command or url"
            return None
        args = spec.get("args") or []
        if not isinstance(args, list):
            args = [str(args)]
        env_spec = spec.get("env") or {}
        env = {k: _resolve_env_value(str(v)) for k, v in env_spec.items()}
        # Inherit PATH so npx/python resolve on Windows
        for k in ("PATH", "PATHEXT", "SYSTEMROOT", "TEMP", "TMP",
                  "USERPROFILE", "APPDATA", "LOCALAPPDATA"):
            if k in os.environ and k not in env:
                env[k] = os.environ[k]

        params = StdioServerParameters(command=command, args=args, env=env)
        client = await self._stack.enter_async_context(
            Client(stdio_client(params))
        )
        print(f"[mcp] {name}: connected via stdio ({command})")
        return client

    async def _discover_tools(self, server: str, client) -> None:
        result = await client.list_tools()
        tools = getattr(result, "tools", None) or []
        trust = False
        try:
            cfg = _load_config()
            trust = bool(cfg["mcpServers"].get(server, {}).get("trust", False))
        except Exception:
            pass
        destructive = not trust

        added = 0
        for tool in tools:
            schema = _mcp_tool_to_ollama_schema(server, tool)
            prefixed = schema["function"]["name"]
            original = getattr(tool, "name", None)
            if not original:
                continue
            self._schemas[prefixed] = schema
            self._tool_map[prefixed] = (server, original)
            self._destructive[prefixed] = destructive
            added += 1

        print(f"[mcp] {server}: {added} tools registered "
              f"({'trusted' if trust else 'destructive'})")

    async def _async_call(self, client, tool_name: str, args: dict) -> str:
        result = await client.call_tool(tool_name, args or {})
        parts: List[str] = []
        for block in (getattr(result, "content", None) or []):
            text = getattr(block, "text", None)
            if text:
                parts.append(text)
        text = "\n".join(parts).strip()
        if not text:
            text = "(empty response)"
        if getattr(result, "is_error", False):
            return f"mcp tool error: {text[:1000]}"
        return text[:8000]


# Module-level singleton, matching the vault/monitor pattern.
mcp = MCPManager()


def start() -> None:
    mcp.start()


def stop() -> None:
    mcp.stop()


def status() -> dict:
    return mcp.status()
