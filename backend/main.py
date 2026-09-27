import asyncio
import json
import os
import re
import shutil
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, Request, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from schemas import ChatRequest, ChatResponse, StatusResponse
from agent import run_agent, clear_working_set
from monitor import monitor
from safety import is_blocked, REFUSAL_MESSAGE
from tools.registry import get_ollama_tools, list_tools, get_connectors, call_tool
from providers import list_providers, get_provider
from audit import recent as audit_recent, stats as audit_stats
from network import allowlist
from secret_store import detect as detect_secret, store as store_secret
import auth
import oauth
import grants as grants_mod


SESSIONS: "OrderedDict[str, list]" = OrderedDict()
SESSION_TS: dict = {}
SESSION_TTL = 3600
SESSION_MAX = 500
HISTORY_MAX = 40
CURRENT_SLOT = settings.DEFAULT_SLOT
CURRENT_MODEL: Optional[str] = None
SELECTION_FILE = Path(__file__).parent / "model_selection.json"

UPLOAD_MAX_BYTES = 500 * 1024 * 1024
MONITOR_MIN_INTERVAL = 60
MONITOR_MAX_INTERVAL = 86400


def _load_selection():
    global CURRENT_SLOT, CURRENT_MODEL
    if not SELECTION_FILE.exists():
        return
    try:
        data = json.loads(SELECTION_FILE.read_text(encoding="utf-8"))
        slot = data.get("slot")
        override = data.get("override")
        if slot and slot in settings.slots:
            CURRENT_SLOT = slot
        if override:
            CURRENT_MODEL = override
    except Exception:
        pass


def _save_selection():
    try:
        SELECTION_FILE.write_text(
            json.dumps({"slot": CURRENT_SLOT, "override": CURRENT_MODEL}),
            encoding="utf-8",
        )
    except Exception:
        pass


def _session_get(sid: str) -> list:
    now = time.time()
    ts = SESSION_TS.get(sid)
    if ts is None or now - ts > SESSION_TTL:
        SESSIONS.pop(sid, None)
        SESSION_TS.pop(sid, None)
        clear_working_set(sid)
        return []
    SESSION_TS[sid] = now
    SESSIONS.move_to_end(sid)
    return SESSIONS.get(sid, [])


def _session_put(sid: str, history: list):
    SESSIONS[sid] = history
    SESSION_TS[sid] = time.time()
    SESSIONS.move_to_end(sid)
    while len(SESSIONS) > SESSION_MAX:
        old, _ = SESSIONS.popitem(last=False)
        SESSION_TS.pop(old, None)
        clear_working_set(old)


def _current_model() -> str:
    if CURRENT_MODEL:
        return CURRENT_MODEL
    return settings.slots.get(CURRENT_SLOT, settings.OLLAMA_MODEL)


def _model_error_reply(err: Exception, model: str) -> str:
    msg = str(err)
    if "not found" in msg.lower() and "model" in msg.lower():
        return (f"Model `{model}` is not downloaded. Run "
                f"`ollama pull {model}` or switch to a different slot.")
    return f"Model error: {msg[:300]}"


class SlotSelectRequest(BaseModel):
    slot: str


class VaultUnlockRequest(BaseModel):
    passphrase: str


class GrantRequest(BaseModel):
    path: str
    label: str = ""
    read: bool = True
    write: bool = True


class GrantRevokeRequest(BaseModel):
    path: str


class CodebaseDisconnectRequest(BaseModel):
    name: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_selection()
    print(f"quill: {len(list_tools())} tools, {len(get_connectors())} connectors")
    print(f"auth: {'enabled' if auth.is_enabled() else 'disabled (no password set)'}")
    yield
    monitor.stop()


app = FastAPI(title="Quill-Cowork", version="0.3.0", lifespan=lifespan)

# ---- CORS: same-origin by default; add extras via env ----
_default_origins = [f"http://localhost:{settings.PORT}", f"http://127.0.0.1:{settings.PORT}"]
_extra = os.getenv("CORS_EXTRA_ORIGINS", "")
_cors_origins = _default_origins + [o.strip() for o in _extra.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# ---- Auth middleware ----
_PUBLIC_PATHS = {"/login", "/health", "/favicon.ico"}


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if not auth.is_enabled():
        return await call_next(request)
    path = request.url.path
    if path in _PUBLIC_PATHS or path.startswith("/static"):
        return await call_next(request)
    if path.startswith("/oauth/google/callback"):
        # Google redirects here directly; the state check protects it
        return await call_next(request)
    if auth.check_request(request):
        return await call_next(request)
    if path == "/" or path.startswith("/api"):
        return RedirectResponse("/login", status_code=302)
    return JSONResponse({"error": "unauthorized"}, status_code=401)


STATIC_DIR = Path(__file__).parent / "static"
WORKSPACE = Path(settings.WORKSPACE_ROOT)
UPLOADS_ROOT = WORKSPACE / ".quill" / "uploads"

ATTACHMENT_RE = re.compile(r"\[attached files?:\s*([^\]]+)\]")
ARCHIVE_EXTS = (".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tar.xz")


def _auto_codebase_path(message: str) -> Optional[str]:
    m = ATTACHMENT_RE.search(message or "")
    if not m:
        return None
    for chunk in m.group(1).split(";"):
        chunk = chunk.strip()
        if " at " not in chunk:
            continue
        p = chunk.rsplit(" at ", 1)[1].strip()
        lp = p.lower()
        if any(lp.endswith(ext) for ext in ARCHIVE_EXTS):
            return p
    return None


@app.get("/login")
async def login_page():
    return HTMLResponse("""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Quill — Sign in</title>
<style>
body{font:15px system-ui;background:#FAF8F4;display:flex;align-items:center;
justify-content:center;min-height:100vh;margin:0;color:#23211D}
form{background:#fff;padding:32px;border:1px solid #E0DACE;border-radius:14px;
box-shadow:0 8px 28px rgba(35,33,29,.08);width:320px}
h1{font:400 22px/1.2 Newsreader,serif;margin:0 0 18px}
input{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid #E0DACE;
border-radius:8px;font:14px system-ui;margin-bottom:14px}
button{width:100%;padding:11px;background:#23211D;color:#FAF8F4;border:none;
border-radius:8px;font:500 14px system-ui;cursor:pointer}
button:hover{background:#3A3731}
.err{color:#B4574A;font-size:13px;margin-bottom:10px}
</style></head><body>
<form method="POST" action="/login">
<h1>Quill Cowork</h1>
<div class="err" id="err"></div>
<input type="password" name="password" placeholder="Password" autofocus required>
<button type="submit">Sign in</button>
</form>
<script>
const e = new URLSearchParams(location.search).get('error');
if (e) document.getElementById('err').textContent = 'Wrong password';
</script>
</body></html>""")


@app.post("/login")
async def login_submit(password: str = Form(...)):
    if not auth.is_enabled():
        return RedirectResponse("/", status_code=302)
    if not auth.verify_password(password):
        return RedirectResponse("/login?error=1", status_code=302)
    tok = auth.issue_token()
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(
        auth.COOKIE_NAME, tok, httponly=True, samesite="lax",
        max_age=auth.SESSION_TTL, path="/",
    )
    return resp


@app.post("/logout")
async def logout(request: Request):
    auth.revoke_token(request.cookies.get(auth.COOKIE_NAME))
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(auth.COOKIE_NAME, path="/")
    return resp


@app.get("/")
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/status", response_model=StatusResponse)
async def status():
    return StatusResponse(
        status="running",
        provider=settings.DEFAULT_PROVIDER,
        tools_count=len(get_ollama_tools()),
        connectors=[c["id"] for c in get_connectors()],
        monitoring=monitor.running,
    )


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    blocked, _ = is_blocked(req.message)
    if blocked:
        return ChatResponse(reply=REFUSAL_MESSAGE, tool_calls=[], session_id=req.session_id)

    detected = detect_secret(req.message)
    if detected:
        vk, val, name = detected
        reply = store_secret(vk, val, name)
        history = _session_get(req.session_id)
        history.append({"role": "user", "content": f"[user provided {name}]"})
        history.append({"role": "assistant", "content": reply})
        _session_put(req.session_id, history[-HISTORY_MAX:])
        return ChatResponse(reply=reply, tool_calls=[], session_id=req.session_id,
                            secret_saved=name)

    auto_path = _auto_codebase_path(req.message)
    if auto_path:
        from tools.codebase import connect_codebase
        try:
            result = connect_codebase(auto_path)
        except Exception as e:
            result = f"connect failed: {type(e).__name__}: {e}"
        history = _session_get(req.session_id)
        history.append({"role": "user", "content": "[connected codebase from attachment]"})
        history.append({"role": "assistant", "content": result})
        _session_put(req.session_id, history[-HISTORY_MAX:])
        return ChatResponse(
            reply=result,
            tool_calls=[{"tool": "connect_codebase",
                         "arguments": {"source": auto_path},
                         "result": result[:500]}],
            session_id=req.session_id,
        )

    history = _session_get(req.session_id)
    model = _current_model()
    try:
        reply, calls = await run_agent(
            req.message, history=history, model=model,
            confirm_callback=None, session_id=req.session_id,
        )
    except Exception as e:
        reply = _model_error_reply(e, model)
        calls = []

    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": reply})
    _session_put(req.session_id, history[-HISTORY_MAX:])

    return ChatResponse(reply=reply, tool_calls=calls, session_id=req.session_id)


@app.get("/tools")
async def list_all_tools():
    return {"tools": get_ollama_tools()}


@app.get("/connectors")
async def list_connectors():
    return {"connectors": get_connectors()}


@app.get("/providers")
async def list_all_providers():
    return {"providers": list_providers(), "default": settings.DEFAULT_PROVIDER}


@app.get("/models/slots")
async def list_slots():
    return {
        "slots": settings.slots,
        "current_slot": CURRENT_SLOT,
        "current_model": settings.slots.get(CURRENT_SLOT, settings.OLLAMA_MODEL),
        "override": CURRENT_MODEL,
        "active_model": _current_model(),
    }


@app.post("/models/slots/select")
async def select_slot(req: SlotSelectRequest):
    global CURRENT_SLOT, CURRENT_MODEL
    if req.slot not in settings.slots:
        return {"ok": False, "error": f"unknown slot: {req.slot}"}
    CURRENT_SLOT = req.slot
    CURRENT_MODEL = None
    _save_selection()
    return {"ok": True, "slot": req.slot, "model": settings.slots[req.slot]}


@app.post("/models/select-raw")
async def select_raw_model(req: SlotSelectRequest):
    global CURRENT_MODEL
    name = (req.slot or "").strip()
    if not name:
        return {"ok": False, "error": "no model name"}
    try:
        available = get_provider().list_models()
    except Exception as e:
        return {"ok": False, "error": f"could not list models: {e}"}
    if name not in available:
        return {"ok": False, "error": f"model not downloaded: {name}"}
    CURRENT_MODEL = name
    _save_selection()
    return {"ok": True, "model": name}


@app.get("/models/current")
async def current_model():
    return {
        "slot": CURRENT_SLOT,
        "model": _current_model(),
        "override": CURRENT_MODEL,
        "slot_model": settings.slots.get(CURRENT_SLOT, settings.OLLAMA_MODEL),
    }


@app.get("/models/available")
async def available_models():
    try:
        return {"models": get_provider().list_models()}
    except Exception as e:
        return {"models": [], "error": str(e)}


@app.get("/widgets/{connector_id}")
async def get_widget(connector_id: str):
    connectors = {c["id"]: c for c in get_connectors()}
    if connector_id not in connectors:
        return {"error": "unknown connector"}
    widget = (connectors[connector_id].get("widgets") or [{}])[0]
    tool = widget.get("tool")
    if not tool:
        return {"value": "-"}
    return {"connector": connector_id, "value": call_tool(tool, {})[:200]}


@app.get("/audit/recent")
async def audit_recent_endpoint(limit: int = 100):
    return {"entries": audit_recent(limit)}


@app.get("/audit/stats")
async def audit_stats_endpoint():
    return audit_stats()


@app.get("/security/layers")
async def security_layers():
    return {
        "layers": [
            {"id": "L1", "name": "Input filter", "enforced": True},
            {"id": "L2", "name": "Tool allowlist", "enforced": True},
            {"id": "L3", "name": "Filesystem sandbox", "enforced": True},
            {"id": "L4", "name": "Confirmation gate", "enforced": True},
            {"id": "L5", "name": "Output filter", "enforced": True},
            {"id": "L6", "name": "Rate limiter", "enforced": True},
            {"id": "L7", "name": "Audit log", "enforced": True},
            {"id": "L8", "name": "Network egress allowlist", "enforced": True},
            {"id": "L9", "name": "Prompt injection detector", "enforced": True},
            {"id": "L10", "name": "Secret redaction", "enforced": True},
            {"id": "L11", "name": "Auth (optional)", "enforced": auth.is_enabled()},
        ]
    }


@app.get("/security/egress")
async def egress_list():
    return {"allowed": sorted(allowlist())}


@app.post("/vault/unlock")
async def vault_unlock(req: VaultUnlockRequest):
    from vault import vault
    if vault.unlock(req.passphrase):
        return {"ok": True}
    return {"ok": False, "error": "wrong passphrase"}


@app.post("/vault/lock")
async def vault_lock():
    from vault import vault
    vault.lock()
    return {"ok": True}


@app.get("/vault/status")
async def vault_status():
    from vault import vault
    try:
        return {
            "passphrase_set": vault.has_passphrase(),
            "locked": vault.is_locked(),
            "keys": vault.keys(),
            "available": vault._load_error is None,
        }
    except RuntimeError as e:
        return {"available": False, "error": str(e)}


@app.get("/oauth/google/start")
async def oauth_google_start():
    if not oauth.is_configured():
        return HTMLResponse(
            "<h2>Gmail is not configured</h2>"
            "<p>Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in backend/.env "
            "and restart the server.</p>",
            status_code=400,
        )
    return RedirectResponse(oauth.google_auth_url())


@app.get("/oauth/google/callback")
async def oauth_google_callback(code: str = "", state: str = "", error: str = ""):
    if error:
        return HTMLResponse(f"<h2>Google returned an error</h2><p>{error}</p>", status_code=400)
    if not code:
        return HTMLResponse("<h2>Missing authorization code</h2>", status_code=400)
    try:
        ok, msg = oauth.exchange_code(code, state=state)
    except Exception as e:
        if "locked" in str(e).lower():
            return HTMLResponse(
                "<h2>Vault is locked</h2>"
                "<p>Unlock the vault first, then restart the flow at "
                "<a href='/oauth/google/start'>/oauth/google/start</a>.</p>",
                status_code=423,
            )
        return HTMLResponse(
            f"<h2>Connection failed</h2><p>{type(e).__name__}: {e}</p>",
            status_code=400,
        )
    if not ok:
        return HTMLResponse(f"<h2>Connection failed</h2><p>{msg}</p>", status_code=400)
    return HTMLResponse(
        "<h2>Gmail connected</h2>"
        "<p>You can close this tab and return to Quill Cowork.</p>"
        "<script>setTimeout(function(){window.close();},1200);</script>"
    )


@app.get("/oauth/status")
async def oauth_status():
    return oauth.status()


@app.post("/oauth/google/disconnect")
async def oauth_google_disconnect():
    oauth.disconnect()
    return {"ok": True}


@app.get("/grants/list")
async def grants_list():
    return {"grants": grants_mod.list_grants()}


@app.post("/grants/grant")
async def grants_grant(req: GrantRequest):
    try:
        entry = grants_mod.add_grant(req.path, label=req.label,
                                      read=req.read, write=req.write)
        return {"ok": True, "grant": entry}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@app.post("/grants/revoke")
async def grants_revoke(req: GrantRevokeRequest):
    ok = grants_mod.remove_grant(req.path)
    return {"ok": ok}


@app.get("/grants/check")
async def grants_check(path: str):
    try:
        p = Path(path).expanduser().resolve()
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {
        "path": str(p),
        "exists": p.exists(),
        "is_dir": p.is_dir() if p.exists() else False,
        "hard_refused": grants_mod.is_hard_refused(str(p)),
        "warned": grants_mod.is_warned(str(p)),
    }


@app.get("/codebase/list")
async def codebase_list():
    import codebase as cb
    return {"codebases": cb.list_codebases()}


@app.post("/codebase/disconnect")
async def codebase_disconnect(req: CodebaseDisconnectRequest):
    import codebase as cb
    if not req.name:
        return {"ok": False, "error": "no name"}
    return {"ok": cb.disconnect(req.name)}


@app.get("/codebase/info")
async def codebase_info_endpoint(name: str):
    import codebase as cb
    meta = cb.get_meta(name)
    if not meta:
        return {"ok": False, "error": "unknown codebase"}
    return {"ok": True, "meta": meta, "tree": cb.get_tree(name, max_lines=300)}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    UPLOADS_ROOT.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in (file.filename or "upload.bin")
                   if c.isalnum() or c in "-_.").strip("-_.")
    if not safe:
        safe = "upload.bin"
    session_dir = UPLOADS_ROOT / uuid.uuid4().hex[:10]
    session_dir.mkdir(parents=True, exist_ok=True)
    target = session_dir / safe
    total = 0
    try:
        with target.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > UPLOAD_MAX_BYTES:
                    out.close()
                    try:
                        target.unlink()
                    except Exception:
                        pass
                    return {"ok": False,
                            "error": f"file exceeds {UPLOAD_MAX_BYTES // (1024*1024)} MB"}
                out.write(chunk)
    except Exception as e:
        try:
            target.unlink()
        except Exception:
            pass
        return {"ok": False, "error": str(e)}
    return {"ok": True, "path": str(target), "name": safe, "size": total}


@app.post("/monitor/start")
async def start_monitor(interval: int = 300):
    interval = max(MONITOR_MIN_INTERVAL, min(int(interval), MONITOR_MAX_INTERVAL))
    monitor.interval = interval

    async def check():
        model = _current_model()
        try:
            reply, _ = await run_agent("Summarize anything new from GitHub.",
                                        model=model, session_id="__monitor__")
        except Exception as e:
            reply = f"monitor error: {type(e).__name__}: {e}"
        return reply

    monitor.set_callback(check)
    monitor.start()
    return {"ok": True, "interval": interval}


@app.post("/monitor/stop")
async def stop_monitor():
    monitor.stop()
    return {"ok": True}


@app.get("/monitor/status")
async def monitor_status():
    return {
        "running": monitor.running,
        "last_run": monitor.last_run,
        "last_result": monitor.last_result,
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # Auth gate: allow same-origin, or cookie, or nothing if auth disabled
    if auth.is_enabled():
        origin = ws.headers.get("origin", "")
        same_origin = origin in _cors_origins
        tok = ws.cookies.get(auth.COOKIE_NAME)
        if not (same_origin or auth.verify_token(tok)):
            await ws.close(code=4401)
            return

    await ws.accept()
    pending: Dict[str, asyncio.Event] = {}
    decisions: Dict[str, bool] = {}
    running: Optional[asyncio.Task] = None

    async def confirm_callback(call_id: str, tool: str, args: dict) -> bool:
        event = asyncio.Event()
        pending[call_id] = event
        decisions[call_id] = False

        await ws.send_json({
            "type": "confirm_request",
            "call_id": call_id,
            "tool": tool,
            "arguments": args,
        })

        try:
            await asyncio.wait_for(event.wait(), timeout=60.0)
        except asyncio.TimeoutError:
            pass

        approved = decisions.pop(call_id, False)
        pending.pop(call_id, None)
        return approved

    async def process(msg: str, sid: str):
        await ws.send_json({"type": "thinking"})

        blocked, _ = is_blocked(msg)
        if blocked:
            await ws.send_json({
                "type": "reply",
                "reply": REFUSAL_MESSAGE,
                "tool_calls": [],
                "session_id": sid,
            })
            return

        detected = detect_secret(msg)
        if detected:
            vk, val, name = detected
            reply = store_secret(vk, val, name)
            history = _session_get(sid)
            history.append({"role": "user", "content": f"[user provided {name}]"})
            history.append({"role": "assistant", "content": reply})
            _session_put(sid, history[-HISTORY_MAX:])
            await ws.send_json({
                "type": "reply",
                "reply": reply,
                "tool_calls": [],
                "session_id": sid,
                "secret_saved": name,
            })
            return

        auto_path = _auto_codebase_path(msg)
        if auto_path:
            from tools.codebase import connect_codebase
            try:
                result = connect_codebase(auto_path)
            except Exception as e:
                result = f"connect failed: {type(e).__name__}: {e}"
            history = _session_get(sid)
            history.append({"role": "user", "content": "[connected codebase from attachment]"})
            history.append({"role": "assistant", "content": result})
            _session_put(sid, history[-HISTORY_MAX:])
            await ws.send_json({
                "type": "reply",
                "reply": result,
                "tool_calls": [{"tool": "connect_codebase",
                                "arguments": {"source": auto_path},
                                "result": result[:500]}],
                "session_id": sid,
            })
            return

        history = _session_get(sid)
        model = _current_model()
        try:
            reply, calls = await run_agent(
                msg, history=history, model=model,
                confirm_callback=confirm_callback, session_id=sid,
            )
        except Exception as e:
            reply = _model_error_reply(e, model)
            calls = []
            await ws.send_json({
                "type": "reply",
                "reply": reply,
                "tool_calls": [],
                "session_id": sid,
            })
            return

        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": reply})
        _session_put(sid, history[-HISTORY_MAX:])

        await ws.send_json({
            "type": "reply",
            "reply": reply,
            "tool_calls": calls,
            "session_id": sid,
        })

    try:
        while True:
            data = await ws.receive_text()
            try:
                payload = json.loads(data)
            except Exception:
                payload = {"message": data}

            if payload.get("type") == "confirm_response":
                cid = payload.get("call_id")
                if cid in pending:
                    decisions[cid] = bool(payload.get("approved"))
                    pending[cid].set()
                continue

            if running and not running.done():
                await ws.send_json({"type": "error", "message": "busy"})
                continue

            sid = payload.get("session_id", "default")
            msg = payload.get("message", "")
            running = asyncio.create_task(process(msg, sid))
    except WebSocketDisconnect:
        if running:
            running.cancel()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)