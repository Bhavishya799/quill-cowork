"""Detect secrets pasted into chat and store them in the vault."""
import re
from typing import Optional, Tuple

from vault import vault


KEY_PATTERNS = [
   (re.compile(r"\btvly-[A-Za-z0-9_\-]{20,}\b"), "TAVILY_API_KEY", "Tavily"),
    (re.compile(r"\bGOCSPX-[A-Za-z0-9_\-]{20,}\b"), "GOOGLE_CLIENT_SECRET", "Google OAuth secret"),
    (re.compile(r"\bghp_[A-Za-z0-9]{36,}\b"), "GITHUB_PERSONAL_ACCESS_TOKEN", "GitHub token"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"), "GITHUB_PERSONAL_ACCESS_TOKEN", "GitHub token"),
    (re.compile(r"\bsk-ant-[A-Za-z0-9\-_]{40,}\b"), "ANTHROPIC_API_KEY", "Anthropic key"),
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "OPENAI_API_KEY", "OpenAI key"),
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9\-]{10,}\b"), "SLACK_TOKEN", "Slack token"),
    (re.compile(r"\bAIza[A-Za-z0-9\-_]{35}\b"), "GOOGLE_API_KEY", "Google API key"),
    (re.compile(r"\bAKIA[A-Z0-9]{16}\b"), "AWS_ACCESS_KEY_ID", "AWS access key"),
    (re.compile(r"\bnvapi-[A-Za-z0-9\-_]{20,}\b"), "NVIDIA_API_KEY", "NVIDIA key"),
    (re.compile(r"\bBSA[A-Za-z0-9\-_]{20,}\b"), "BRAVE_API_KEY", "Brave API key"),
]

GENERIC_HIGH_ENTROPY = re.compile(r"\b[A-Za-z0-9_\-]{32,}\b")

CONTEXT_WORDS = re.compile(
    r"\b(api[\s_-]?key|token|secret|credential|password)\b",
    re.IGNORECASE,
)

SAVE_INTENT = re.compile(
    r"\b(save|store|add|set|here('s| is)|this is|use this)\b.{0,60}"
    r"\b(api[\s_-]?key|token|secret|key|credential)\b",
    re.IGNORECASE,
)


def _infer_name(message: str, default: str) -> Tuple[str, str]:
    ctx = message.lower()
    if "tavily" in ctx:
        return "TAVILY_API_KEY", "Tavily"
    if "brave" in ctx:
        return "BRAVE_API_KEY", "Brave"
    if "openai" in ctx:
        return "OPENAI_API_KEY", "OpenAI"
    if "anthropic" in ctx or "claude" in ctx:
        return "ANTHROPIC_API_KEY", "Anthropic"
    if "nvidia" in ctx:
        return "NVIDIA_API_KEY", "NVIDIA"
    if "slack" in ctx:
        return "SLACK_TOKEN", "Slack"
    if "aws" in ctx:
        return "AWS_ACCESS_KEY_ID", "AWS"
    if "github" in ctx:
        return "GITHUB_PERSONAL_ACCESS_TOKEN", "GitHub"
    if "google" in ctx and ("secret" in ctx or "oauth" in ctx):
        return "GOOGLE_CLIENT_SECRET", "Google OAuth secret"
    if "google" in ctx:
        return "GOOGLE_API_KEY", "Google API key"
    return default, "API key"


def detect(message: str) -> Optional[Tuple[str, str, str]]:
    """Return (vault_key, value, human_name) if the message contains a secret."""
    if not message:
        return None

    for pattern, vault_key, name in KEY_PATTERNS:
        m = pattern.search(message)
        if m:
            return vault_key, m.group(0), name

    if SAVE_INTENT.search(message) or CONTEXT_WORDS.search(message):
        m = GENERIC_HIGH_ENTROPY.search(message)
        if m:
            vk, name = _infer_name(message, "API_KEY_UNKNOWN")
            return vk, m.group(0), name

    return None


def store(vault_key: str, value: str, human_name: str) -> str:
    """Store a detected secret in the vault. Returns a user-facing reply."""
    try:
        if vault.has_passphrase():
            if vault.is_locked():
                return ("Your vault is locked. Unlock it first "
                        "(`vault.py unlock <passphrase>`) and paste the key again.")
            vault.set(vault_key, value, sensitive=True)
            return (f"Saved your {human_name}. It's encrypted with your passphrase "
                    f"in the vault. It won't appear in chat history.")
        else:
            vault.set(vault_key, value, sensitive=False)
            return (f"Saved your {human_name}. It's encrypted in the vault. "
                    f"Consider setting a vault passphrase for an extra layer.")
    except Exception as e:
        return f"Could not save the {human_name}: {e}"