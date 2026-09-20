"""Onyx configuration — reads from .env."""

import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "ollama")

    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "8"))


settings = Settings()