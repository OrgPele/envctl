from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from io import StringIO
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.command_router import list_supported_commands
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
import envctl_engine.runtime.engine_runtime as engine_runtime_module
import envctl_engine.runtime.engine_runtime_startup_support as startup_support
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.test_output.parser_base import strip_ansi


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True



class EngineRuntimeCommandParityTestCase(unittest.TestCase):
    def _runtime(self) -> PythonEngineRuntime:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
            }
        )
        return PythonEngineRuntime(config, env={})

__all__ = [
    "EngineRuntimeCommandParityTestCase",
    "Path",
    "ProjectStartupResult",
    "PYTHON_ROOT",
    "PythonEngineRuntime",
    "REPO_ROOT",
    "RunState",
    "ServiceRecord",
    "SimpleNamespace",
    "StringIO",
    "_TtyStringIO",
    "engine_runtime_module",
    "json",
    "load_config",
    "list_supported_commands",
    "parse_route",
    "patch",
    "redirect_stdout",
    "startup_support",
    "strip_ansi",
    "subprocess",
    "tempfile",
    "unittest",
]
