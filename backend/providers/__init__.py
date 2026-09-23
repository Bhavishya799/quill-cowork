import os

from .base import BaseProvider
from .ollama_provider import OllamaProvider


_providers = {}


def register_provider(provider: BaseProvider):
    _providers[provider.name] = provider


def get_provider(name: str = None) -> BaseProvider:
    if name is None:
        name = os.getenv("DEFAULT_PROVIDER", "ollama")
    if name not in _providers:
        raise KeyError(f"unknown provider: {name}")
    return _providers[name]


def list_providers() -> list:
    return list(_providers.keys())


register_provider(OllamaProvider())