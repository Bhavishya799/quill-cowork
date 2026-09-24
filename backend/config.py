import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    DEFAULT_PROVIDER = os.getenv("DEFAULT_PROVIDER", "ollama")
    OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")

    MODEL_FAST = os.getenv("MODEL_FAST", "qwen2.5:3b")
    MODEL_BALANCED = os.getenv("MODEL_BALANCED", "quill")
    MODEL_POWERFUL = os.getenv("MODEL_POWERFUL", "qwen2.5:7b")
    MODEL_CPU_FAST = os.getenv("MODEL_CPU_FAST", "quill-cpu-fast")
    MODEL_CPU_SMART = os.getenv("MODEL_CPU_SMART", "quill-cpu-smart")
    DEFAULT_SLOT = os.getenv("DEFAULT_SLOT", "balanced")

    OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", MODEL_BALANCED)

    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))
    MAX_TOOL_ITERATIONS = int(os.getenv("MAX_TOOL_ITERATIONS", "8"))

    @property
    def slots(self):
        return {
            "fast": self.MODEL_FAST,
            "balanced": self.MODEL_BALANCED,
            "powerful": self.MODEL_POWERFUL,
            "cpu-fast": self.MODEL_CPU_FAST,
            "cpu-smart": self.MODEL_CPU_SMART,
        }


settings = Settings()