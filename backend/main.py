"""Onyx backend — FastAPI server."""
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path
import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from config import settings
from schemas import ChatRequest, ChatResponse, StatusResponse
from agent import run_agent
from monitor import monitor
from tools.registry import get_ollama_tools, list_tools, get_connectors
from providers import list_providers


SESSIONS: dict = {}
# Active model slot (can be changed at runtime via /models/slots/select)
CURRENT_SLOT = settings.DEFAULT_SLOT


class SlotSelectRequest(BaseModel):
    slot: str  # "fast" | "balanced" | "powerful"
app = FastAPI(title="Onyx API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# Serve the frontend
STATIC_DIR = Path(__file__).parent / "static"

@app.get("/")
async def serve_index():
    return FileResponse(STATIC_DIR / "index.html")

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.on_event("startup")
async def on_startup():
    print("[Onyx] Backend starting...")
    print(f"[Onyx] Providers: {', '.join(list_providers())}")
    print(f"[Onyx] Tools: {', '.join(list_tools())}")
    print(f"[Onyx] Connectors: {', '.join(c['id'] for c in get_connectors())}")


@app.on_event("shutdown")
async def on_shutdown():
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
    history = SESSIONS.get(req.session_id, [])
    slot_model = settings.get_slots().get(CURRENT_SLOT, settings.OLLAMA_MODEL)
    reply, tool_calls = await run_agent(req.message, history=history, model=slot_model)


@app.get("/tools")
async def list_all_tools():
    return {"tools": get_ollama_tools()}


@app.get("/connectors")
async def list_connectors():
    return {"connectors": get_connectors()}


@app.get("/providers")
async def list_all_providers():
    return {"providers": list_providers(), "default": settings.DEFAULT_PROVIDER}


@app.post("/monitor/start")
async def start_monitor(interval: int = 300):
    monitor.interval = interval

    async def check():
        reply, _ = await run_agent("Summarize anything new from GitHub notifications.")
        return reply

    monitor.set_callback(check)
    monitor.start()
    return {"ok": True, "running": True}


@app.post("/monitor/stop")
async def stop_monitor():
    monitor.stop()
    return {"ok": True, "running": False}


@app.get("/monitor/status")
async def monitor_status():
    return {
        "running": monitor.running,
        "last_run": monitor.last_run,
        "last_result": monitor.last_result,
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            data = await ws.receive_text()
            try:
                payload = json.loads(data)
            except Exception:
                payload = {"message": data}

            session_id = payload.get("session_id", "default")
            user_msg = payload.get("message", "")

            await ws.send_json({"type": "thinking"})

            history = SESSIONS.get(session_id, [])
            slot_model = settings.get_slots().get(CURRENT_SLOT, settings.OLLAMA_MODEL)
            reply, tool_calls = await run_agent(user_msg, history=history, model=slot_model)

            history.append({"role": "user", "content": user_msg})
            history.append({"role": "assistant", "content": reply})
            SESSIONS[session_id] = history[-20:]

            await ws.send_json({
                "type": "reply",
                "reply": reply,
                "tool_calls": tool_calls,
                "session_id": session_id,
            })
    except WebSocketDisconnect:
        pass

@app.get("/widgets/{connector_id}")
async def get_widget(connector_id: str):
    """Run a connector's widget tool and return the raw output."""
    from tools.registry import get_connectors, call_tool
    connectors = {c["id"]: c for c in get_connectors()}
    if connector_id not in connectors:
        return {"error": "unknown connector"}
    widget = (connectors[connector_id].get("widgets") or [{}])[0]
    tool_name = widget.get("tool")
    if not tool_name:
        return {"value": "—"}
    result = call_tool(tool_name, {})
    return {"connector": connector_id, "widget": widget, "value": result[:200]}
    # ============================================================
# MODEL SLOTS
# ============================================================
@app.get("/models/slots")
async def list_slots():
    """Return the three model slots and which one is active."""
    slots = settings.get_slots()
    return {
        "slots": slots,
        "current_slot": CURRENT_SLOT,
        "current_model": slots.get(CURRENT_SLOT, settings.OLLAMA_MODEL),
    }


@app.post("/models/slots/select")
async def select_slot(req: SlotSelectRequest):
    global CURRENT_SLOT
    slots = settings.get_slots()
    if req.slot not in slots:
        return {"ok": False, "error": f"Unknown slot '{req.slot}'. Use: fast, balanced, powerful"}
    CURRENT_SLOT = req.slot
    print(f"[Quill] Active slot switched to '{req.slot}' → {slots[req.slot]}")
    return {"ok": True, "slot": req.slot, "model": slots[req.slot]}


@app.get("/models/available")
async def available_models():
    """List every model currently installed in Ollama (for advanced users)."""
    try:
        provider = get_provider()
        return {"models": provider.list_models()}
    except Exception as e:
        return {"models": [], "error": str(e)}
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)