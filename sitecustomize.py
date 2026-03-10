from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent
PYTHON_ROOT = REPO_ROOT / "python"

if PYTHON_ROOT.is_dir():
    python_root_str = str(PYTHON_ROOT)
    if python_root_str in sys.path:
        sys.path.remove(python_root_str)
    sys.path.insert(0, python_root_str)
