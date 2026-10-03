"""Quill Core - shared utilities.

Three submodules, no third-party dependencies at import time. Each
submodule imports its optional dependency lazily inside a function so
that a missing or broken library degrades to a fallback instead of
crashing the package.
"""
from . import files
from . import markdown
from . import parsing

__all__ = ["files", "markdown", "parsing"]
__version__ = "0.1.0"
