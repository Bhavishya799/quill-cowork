import importlib
import os
import pkgutil
from pathlib import Path


_SKIP = {"registry", "__init__"}


def load_all_tools():
    disabled = {
        c.strip()
        for c in (os.getenv("DISABLED_CONNECTORS", "") or "").split(",")
        if c.strip()
    }
    skip = _SKIP | disabled

    loaded, failed = [], []
    folder = Path(__file__).parent

    for _, name, _ in pkgutil.iter_modules([str(folder)]):
        if name.startswith("_") or name in skip:
            continue
        try:
            importlib.import_module(f"tools.{name}")
            loaded.append(name)
        except Exception as e:
            failed.append((name, str(e)))
            print(f"[tools] failed to load {name}: {e}")

    print(f"[tools] loaded: {', '.join(sorted(loaded)) or 'none'}")
    return loaded, failed