"""Structured tool results."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class ToolResult:
    ok: bool
    data: str = ""
    error: str = ""
    status: str = "succeeded"

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "data": self.data,
                "error": self.error, "status": self.status}

    def content(self) -> str:
        if self.ok:
            return self.data or "(empty)"
        return self.error or "tool failed"


def succeeded(data: str) -> ToolResult:
    return ToolResult(ok=True, data=data, status="succeeded")


def failed(error: str) -> ToolResult:
    return ToolResult(ok=False, error=error, status="failed")


def denied(reason: str = "User declined this action.") -> ToolResult:
    return ToolResult(ok=False, error=reason, status="denied")


def rate_limited(reason: str) -> ToolResult:
    return ToolResult(ok=False, error=reason, status="rate_limited")


def disabled(reason: str) -> ToolResult:
    return ToolResult(ok=False, error=reason, status="disabled")
