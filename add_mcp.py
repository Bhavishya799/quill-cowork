"""add_mcp.py - Model Context Protocol client for Quill-Cowork.

Adds:
  backend/mcp_client.py       - MCP manager (connect, discover, call)
  backend/mcp_servers.json    - server config (empty by default)
  backend/tools/registry.py   - register_external_tool() helper
  backend/main.py             - MCP lifecycle in lifespan, /mcp/status
  backend/agent.py            - router rule for mcp_* tools
  backend/requirements.txt    - mcp>=2.0.0
  .gitignore                  - mcp_servers.local.json

Idempotent. Run from D:\\Quill-Cowork:  python add_mcp.py
"""
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).parent.resolve()
BACKEND = ROOT / "backend"

if not BACKEND.is_dir():
    print(f"ERROR: {BACKEND} not found")
    sys.exit(1)

_log = []
def note(msg, kind="ok"):
    _log.append((msg, kind))
    tag = {"ok": "[OK]  ", "skip": "[SKIP]", "warn": "[WARN]"}.get(kind, "[?]   ")
    print(f"{tag} {msg}")


# =====================================================================
# 1. backend/mcp_client.py
# =====================================================================
MCP_CLIENT = r'''"""MCP client manager.

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


import re  # noqa: E402  (used by _resolve_env_value)


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
        trust = bool(spec.get("trust", False))
        destructive = not trust

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
'''

p = BACKEND / "mcp_client.py"
if not p.exists() or "class MCPManager" not in p.read_text(encoding="utf-8"):
    p.write_text(MCP_CLIENT, encoding="utf-8")
    note("wrote backend/mcp_client.py")
else:
    note("backend/mcp_client.py already present", "skip")


# =====================================================================
# 2. backend/mcp_servers.json
# =====================================================================
MCP_CONFIG = '''{
  "_comment": "Add MCP servers under mcpServers. Stdio: {command, args, env}. HTTP: {url, transport}. Set trust=true to skip confirmation.",
  "_example_stdio": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "D:/Quill-Cowork/workspace"],
      "trust": false
    }
  },
  "_example_http": {
    "remote": {
      "url": "https://example.com/mcp",
      "transport": "http",
      "trust": false
    }
  },
  "mcpServers": {}
}
'''

cfg_path = BACKEND / "mcp_servers.json"
if not cfg_path.exists():
    cfg_path.write_text(MCP_CONFIG, encoding="utf-8")
    note("wrote backend/mcp_servers.json (empty)")
else:
    note("backend/mcp_servers.json already present", "skip")


# =====================================================================
# 3. tools/registry.py - register_external_tool
# =====================================================================
REG = BACKEND / "tools" / "registry.py"
src = REG.read_text(encoding="utf-8")

if "def register_external_tool" not in src:
    anchor = "def get_ollama_tools() -> List[Dict[str, Any]]:"
    if anchor in src:
        block = '''def register_external_tool(name: str, schema: Dict[str, Any],
                             caller, destructive: bool = True) -> None:
    """Register a tool whose implementation lives outside this process.
    Used for MCP tools. `caller` must accept **kwargs and return str."""
    _tools[name] = {
        "function": caller,
        "destructive": destructive,
        "schema": schema,
        "external": True,
    }


def unregister_external_tools(prefix: str) -> int:
    """Remove all tools whose name starts with prefix. Returns count."""
    names = [n for n in _tools if n.startswith(prefix)]
    for n in names:
        _tools.pop(n, None)
    return len(names)


'''
        src = src.replace(anchor, block + anchor, 1)
        REG.write_text(src, encoding="utf-8")
        note("tools/registry.py: register_external_tool")
    else:
        note("tools/registry.py: anchor missing", "warn")
else:
    note("tools/registry.py: already has external helpers", "skip")


# =====================================================================
# 4. main.py - lifespan + /mcp/status
# =====================================================================
MAIN = BACKEND / "main.py"
src = MAIN.read_text(encoding="utf-8")
changed = False

if "import mcp_client" not in src:
    src = src.replace(
        "import chat_store\n",
        "import chat_store\nimport mcp_client\n",
        1,
    )
    changed = True
    note("main.py: import mcp_client")

if "mcp_client.start()" not in src:
    # Add a helper that registers MCP tools into the registry
    helper_anchor = "@asynccontextmanager\nasync def lifespan(app: FastAPI):"
    if helper_anchor in src:
        helper = '''def _register_mcp_tools():
    """Pull MCP tool schemas into the local registry."""
    from tools.registry import register_external_tool
    schemas = mcp_client.mcp.get_schemas()
    for schema in schemas:
        name = schema["function"]["name"]
        destructive = mcp_client.mcp.get_destructive(name)
        def _caller(_name=name, **kw):
            return mcp_client.mcp.call_tool_sync(_name, kw)
        register_external_tool(
            name, schema, _caller, destructive=destructive
        )
    return len(schemas)


'''
        src = src.replace(helper_anchor, helper + helper_anchor, 1)
        changed = True
        note("main.py: _register_mcp_tools helper")

    # Start MCP in lifespan
    old_life = '''    _load_selection()
    print(f"quill: {len(list_tools())} tools, {len(get_connectors())} connectors")'''
    new_life = '''    _load_selection()
    mcp_client.start()
    n_mcp = _register_mcp_tools()
    if n_mcp:
        print(f"mcp: {n_mcp} tools registered")
    print(f"quill: {len(list_tools())} tools, {len(get_connectors())} connectors")'''
    if old_life in src:
        src = src.replace(old_life, new_life, 1)
        changed = True
        note("main.py: lifespan starts MCP")

    # Stop MCP on shutdown
    if "mcp_client.stop()" not in src:
        src = src.replace(
            "    yield\n    monitor.stop()",
            "    yield\n    monitor.stop()\n    mcp_client.stop()",
            1,
        )
        changed = True
        note("main.py: lifespan stops MCP")

# /mcp/status endpoint
if "/mcp/status" not in src:
    anchor = '@app.get("/tools")'
    if anchor in src:
        block = '''@app.get("/mcp/status")
async def mcp_status():
    return mcp_client.status()


@app.post("/mcp/reload")
async def mcp_reload():
    """Restart the MCP manager with the current config file."""
    from tools.registry import unregister_external_tools
    unregister_external_tools("mcp_")
    mcp_client.stop()
    mcp_client.start()
    n = _register_mcp_tools()
    return {"ok": True, "tools": n}


'''
        src = src.replace(anchor, block + anchor, 1)
        changed = True
        note("main.py: /mcp/status + /mcp/reload")

if changed:
    MAIN.write_text(src, encoding="utf-8")


# =====================================================================
# 5. agent.py - router offers mcp_* tools when server name matches
# =====================================================================
AGENT = BACKEND / "agent.py"
src = AGENT.read_text(encoding="utf-8")

if "# MCP router rule" not in src:
    anchor = "    # ---- Filesystem ----"
    if anchor in src:
        block = '''    # MCP router rule: offer mcp_<server>_* tools when the user names
    # the server (e.g. "use filesystem to read X").
    _mcp_seen = set()
    for t in all_tools:
        _n = t["function"]["name"]
        if not _n.startswith("mcp_"):
            continue
        _parts = _n.split("_", 2)
        if len(_parts) < 3:
            continue
        _server = _parts[1]
        if _server in _mcp_seen:
            continue
        if re.search(rf"\\b{re.escape(_server)}\\b", m):
            _mcp_seen.add(_server)
            for t2 in all_tools:
                if t2["function"]["name"].startswith(f"mcp_{_server}_"):
                    keep.add(t2["function"]["name"])

'''
        src = src.replace(anchor, block + anchor, 1)
        AGENT.write_text(src, encoding="utf-8")
        note("agent.py: MCP router rule")
    else:
        note("agent.py: Filesystem anchor missing", "warn")
else:
    note("agent.py: MCP router rule already present", "skip")


# =====================================================================
# 6. requirements.txt
# =====================================================================
REQ = BACKEND / "requirements.txt"
req = REQ.read_text(encoding="utf-8") if REQ.exists() else ""
if "mcp" not in req.splitlines() and not any(
    line.strip().startswith("mcp") for line in req.splitlines()
):
    req = req.rstrip() + "\nmcp>=2.0.0\n"
    REQ.write_text(req, encoding="utf-8")
    note("requirements.txt: mcp>=2.0.0")
else:
    note("requirements.txt: mcp already present", "skip")


# =====================================================================
# 7. .gitignore
# =====================================================================
GI = ROOT / ".gitignore"
if GI.exists():
    src = GI.read_text(encoding="utf-8")
    if "mcp_servers.local.json" not in src:
        src = src.rstrip() + (
            "\n\n# MCP: local server configs with secrets\n"
            "mcp_servers.local.json\n"
            "backend/mcp_servers.local.json\n"
        )
        GI.write_text(src, encoding="utf-8")
        note(".gitignore: mcp_servers.local.json")
    else:
        note(".gitignore already updated", "skip")


# =====================================================================
# 8. Verify
# =====================================================================
print()
print("=" * 60)
print("Verification")
print("=" * 60)

r = subprocess.run(
    [sys.executable, "-c",
     "import sys; sys.path.insert(0,'backend'); "
     "import mcp_client; "
     "print('manager class:', hasattr(mcp_client, 'MCPManager')); "
     "print('singleton:', hasattr(mcp_client, 'mcp')); "
     "from tools.registry import register_external_tool; "
     "print('registry helper:', callable(register_external_tool))"],
    cwd=str(ROOT), capture_output=True, text=True,
)
for line in (r.stdout or "").strip().splitlines():
    print(f"  {line}")
if r.returncode != 0:
    print("  [FAIL] import error:")
    for line in (r.stderr or "").strip().splitlines()[-8:]:
        print("  " + line)

print()
print("=" * 60)
print("Summary")
print("=" * 60)
print("  Added:")
print("    backend/mcp_client.py       MCP manager")
print("    backend/mcp_servers.json    server config (empty)")
print("  Patched:")
print("    tools/registry.py           register_external_tool")
print("    main.py                     lifespan + /mcp/status + /mcp/reload")
print("    agent.py                    router rule for mcp_* tools")
print("    requirements.txt            mcp>=2.0.0")
print("    .gitignore                  mcp_servers.local.json")
print()
print("Next:")
print("  1. Install:  pip install -r backend\\requirements.txt")
print("  2. Configure: edit backend\\mcp_servers.json")
print("  3. Start:    python backend\\main.py")
print("  4. Check:    curl http://localhost:8000/mcp/status")
print("=" * 60)