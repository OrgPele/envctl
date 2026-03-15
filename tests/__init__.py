"""Test package."""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = (REPO_ROOT / "python").resolve()


def _loaded_from_other_checkout(module_name: str) -> bool:
    module = sys.modules.get(module_name)
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return False
    try:
        module_path = Path(module_file).resolve()
    except OSError:
        return False
    return PYTHON_ROOT not in module_path.parents


if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

for name in list(sys.modules):
    if name == "envctl_engine" or name.startswith("envctl_engine."):
        if _loaded_from_other_checkout(name):
            del sys.modules[name]
