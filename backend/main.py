"""Onyx backend — FastAPI server."""
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
    reply, tool_calls = await run_agent(req.message, history=history)
    history.append({"role": "user", "content": req.message})
    history.append({"role": "assistant", "content": reply})
    SESSIONS[req.session_id] = history[-20:]
    return ChatResponse(reply=reply, tool_calls=tool_calls, session_id=req.session_id)


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
            reply, tool_calls = await run_agent(user_msg, history=history)

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
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=True)