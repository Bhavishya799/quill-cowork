import os
import time
from typing import List, Generator

import ollama

from .base import BaseProvider


class OllamaProvider(BaseProvider):
    name = "ollama"

    def __init__(self):
        self.default_model = os.getenv("OLLAMA_MODEL", "quill")
        try:
            self.timeout = float(os.getenv("OLLAMA_TIMEOUT", "120"))
        except ValueError:
            self.timeout = 120.0
        self.client = ollama.Client(
            host=os.getenv("OLLAMA_HOST", "http://localhost:11434"),
            timeout=self.timeout,
        )

    def chat(self, messages, tools=None, model=None, format=None, stream=False):
        last_error = None
        for attempt in range(3):
            try:
                kwargs = dict(
                    model=model or self.default_model,
                    messages=messages,
                    tools=tools or None,
                    think=False,
                    options={
                        "num_ctx": int(os.getenv("OLLAMA_NUM_CTX", "8192")),
                        "num_predict": 2048,
                        "temperature": 0.2,
                        "top_p": 0.9,
                        "repeat_penalty": 1.15,
                    },
                )
                if format is not None:
                    kwargs["format"] = format
                
                if stream:
                    response = self.client.chat(**kwargs, stream=True)
                    for chunk in response:
                        yield chunk["message"]
                    return

                response = self.client.chat(**kwargs)
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