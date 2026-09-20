"""Onyx provider registry — local-only for now."""

import os

from .base import BaseProvider
from .ollama_provider import OllamaProvider


_PROVIDERS = {}


def register_provider(provider: BaseProvider):
    _PROVIDERS[provider.name] = provider


def get_provider(name: str = None) -> BaseProvider:
    if name is None:
        name = os.getenv("DEFAULT_PROVIDER", "ollama")
    if name not in _PROVIDERS:
        raise KeyError(f"Provider '{name}' not registered. Available: {list(_PROVIDERS.keys())}")
    return _PROVIDERS[name]


def list_providers() -> list:
    return list(_PROVIDERS.keys())


register_provider(OllamaProvider())