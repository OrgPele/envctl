from __future__ import annotations

import sys
from pathlib import Path


def repo_root_from(path: str) -> Path:
    return Path(path).resolve().parents[1]


def ensure_python_root(repo_root: Path) -> Path:
    python_root = repo_root / "python"
    python_root_str = str(python_root)
    if python_root_str not in sys.path:
        sys.path.insert(0, python_root_str)
    return python_root
