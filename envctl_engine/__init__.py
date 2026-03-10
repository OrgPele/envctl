"""Checkout-local package shim for the source tree under ``python/``."""

from __future__ import annotations

from pathlib import Path


_SOURCE_PACKAGE_ROOT = Path(__file__).resolve().parent.parent / "python" / "envctl_engine"

__path__ = [str(_SOURCE_PACKAGE_ROOT)]
__file__ = str(_SOURCE_PACKAGE_ROOT / "__init__.py")
