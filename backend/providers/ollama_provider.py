"""Ollama provider — local models."""

import os
from typing import List, Dict, Any, Optional

import ollama

from .base import BaseProvider


class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self, host: Optional[str] = None, default_model: Optional[str] = None):
        self.host = host or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        self.default_model = default_model or os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
        self.client = ollama.Client(host=self.host)

    def chat(self, messages, tools=None, model=None):
        response = self.client.chat(
            model=model or self.default_model,
            messages=messages,
            tools=tools if tools else None,
        )
        msg = response["message"]
        return {
            "role": msg.get("role", "assistant"),
            "content": msg.get("content", "") or "",
            "tool_calls": msg.get("tool_calls") or [],
        }

    def list_models(self) -> List[str]:
        try:
            result = self.client.list()
            return [m["model"] for m in result.get("models", [])]
        except Exception:
            return []