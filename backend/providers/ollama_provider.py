import os
import time
from typing import List

import ollama

from .base import BaseProvider


class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self):
        self.default_model = os.getenv("OLLAMA_MODEL", "quill")
        self.client = ollama.Client(host=os.getenv("OLLAMA_HOST", "http://localhost:11434"))

    def chat(self, messages, tools=None, model=None):
        last_error = None
        for attempt in range(3):
            try:
                response = self.client.chat(
                    model=model or self.default_model,
                    messages=messages,
                    tools=tools or None,
                )
                msg = response["message"]
                return {
                    "role": msg.get("role", "assistant"),
                    "content": msg.get("content", "") or "",
                    "tool_calls": msg.get("tool_calls") or [],
                }
            except Exception as e:
                last_error = e
                if attempt < 2:
                    time.sleep(2 ** attempt)
        raise last_error

    def list_models(self) -> List[str]:
        try:
            return [m["model"] for m in self.client.list().get("models", [])]
        except Exception:
            return []