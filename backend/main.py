import asyncio
import json
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from schemas import ChatRequest, ChatResponse, StatusResponse
from agent import run_agent
from monitor import monitor
from safety import is_blocked, REFUSAL_MESSAGE
from tools.registry import get_ollama_tools, list_tools, get_connectors, call_tool
from providers import list_providers, get_provider
from audit import recent as audit_recent, stats as audit_stats
from network import allowlist


SESSIONS: Dict[str, list] = {}
CURRENT_SLOT = settings.DEFAULT_SLOT


class SlotSelectRequest(BaseModel):
    slot: str


app = FastAPI(title="Quill-Cowork", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = Path(__file__).parent / "static"


@app.get("/")
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
async def startup():
    print(f"quill: {len(list_tools())} tools, {len(get_connectors())} connectors")


@app.on_event("shutdown")
async def shutdown():
    monitor.stop()


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
    blocked, reason = is_blocked(req.message)
    if blocked:
        return ChatResponse(reply=REFUSAL_MESSAGE, tool_calls=[], session_id=req.session_id)

    history = SESSIONS.get(req.session_id, [])
    model = settings.slots.get(CURRENT_SLOT, settings.OLLAMA_MODEL)
    reply, calls = await run_agent(req.message, history=history, model=model, confirm_callback=None)

    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": reply})
    SESSIONS[req.session_id] = history[-20:]

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
    }


@app.post("/models/slots/select")
async def select_slot(req: SlotSelectRequest):
    global CURRENT_SLOT
    if req.slot not in settings.slots:
        return {"ok": False, "error": f"unknown slot: {req.slot}"}
    CURRENT_SLOT = req.slot
    return {"ok": True, "slot": req.slot, "model": settings.slots[req.slot]}


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
            {"id": "L1", "name": "Input filter", "enforced": False},
            {"id": "L2", "name": "Tool allowlist", "enforced": True},
            {"id": "L3", "name": "Filesystem sandbox", "enforced": True},
            {"id": "L4", "name": "Confirmation gate", "enforced": True},
            {"id": "L5", "name": "Output filter", "enforced": True},
            {"id": "L6", "name": "Rate limiter", "enforced": True},
            {"id": "L7", "name": "Audit log", "enforced": True},
            {"id": "L8", "name": "Network egress allowlist", "enforced": True},
            {"id": "L9", "name": "Prompt injection detector", "enforced": True},
            {"id": "L10", "name": "Secret redaction", "enforced": True},
        ]
    }


@app.get("/security/egress")
async def egress_list():
    return {"allowed": sorted(allowlist())}


@app.post("/monitor/start")
async def start_monitor(interval: int = 300):
    monitor.interval = interval

    async def check():
        reply, _ = await run_agent("Summarize anything new from GitHub.")
        return reply

    monitor.set_callback(check)
    monitor.start()
    return {"ok": True}


@app.post("/monitor/stop")
async def stop_monitor():
    monitor.stop()
    return {"ok": True}


@app.get("/monitor/status")
async def monitor_status():
    return {"running": monitor.running, "last_run": monitor.last_run}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
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

        blocked, reason = is_blocked(msg)
        if blocked:
            await ws.send_json({
                "type": "reply",
                "reply": REFUSAL_MESSAGE,
                "tool_calls": [],
                "session_id": sid,
            })
            return

        history = SESSIONS.get(sid, [])
        model = settings.slots.get(CURRENT_SLOT, settings.OLLAMA_MODEL)
        reply, calls = await run_agent(
            msg, history=history, model=model, confirm_callback=confirm_callback
        )

        history.append({"role": "user", "content": msg})
        history.append({"role": "assistant", "content": reply})
        SESSIONS[sid] = history[-20:]

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
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)