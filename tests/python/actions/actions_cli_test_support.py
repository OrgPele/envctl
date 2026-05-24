from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from envctl_engine.test_output.parser_base import strip_ansi

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
actions_cli = importlib.import_module("envctl_engine.actions.actions_cli")

__all__ = [
    "Path",
    "PYTHON_ROOT",
    "REPO_ROOT",
    "StringIO",
    "_TtyStringIO",
    "actions_cli",
    "importlib",
    "json",
    "os",
    "patch",
    "redirect_stdout",
    "strip_ansi",
    "subprocess",
    "sys",
    "tempfile",
    "types",
    "unittest",
]


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True
