from pydantic import BaseModel
from typing import Optional, List, Dict, Any


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = "default"


class ChatResponse(BaseModel):
    reply: str
    tool_calls: List[Dict[str, Any]] = []
    session_id: str


class StatusResponse(BaseModel):
    status: str
    provider: str
    tools_count: int
    connectors: List[str] = []
    monitoring: bool