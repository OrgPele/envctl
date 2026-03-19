"""Python test package."""

from __future__ import annotations

from pathlib import Path

from scripts._bootstrap import ensure_python_root

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON_ROOT = ensure_python_root(REPO_ROOT)
