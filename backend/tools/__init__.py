import importlib
import pkgutil
from pathlib import Path


_SKIP = {"registry", "__init__"}


def load_all_tools():
    loaded, failed = [], []
    folder = Path(__file__).parent

    for _, name, _ in pkgutil.iter_modules([str(folder)]):
        if name.startswith("_") or name in _SKIP:
            continue
        try:
            importlib.import_module(f"tools.{name}")
            loaded.append(name)
        except Exception as e:
            failed.append((name, str(e)))
            print(f"[tools] failed to load {name}: {e}")

    print(f"[tools] loaded: {', '.join(sorted(loaded)) or 'none'}")
    return loaded, failed