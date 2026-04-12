from __future__ import annotations

import sys
from pathlib import Path


def repo_root_from(path: str) -> Path:
    return Path(path).resolve().parents[1]


def _loaded_from_other_checkout(module_name: str, *, python_root: Path) -> bool:
    module = sys.modules.get(module_name)
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return False
    try:
        module_path = Path(module_file).resolve()
    except OSError:
        return False
    return python_root not in module_path.parents


def ensure_python_root(repo_root: Path) -> Path:
    python_root = (repo_root / "python").resolve()
    python_root_str = str(python_root)
    sys.path[:] = [entry for entry in sys.path if entry != python_root_str]
    sys.path.insert(0, python_root_str)
    for name in list(sys.modules):
        if name == "envctl_engine" or name.startswith("envctl_engine."):
            if _loaded_from_other_checkout(name, python_root=python_root):
                del sys.modules[name]
    return python_root
