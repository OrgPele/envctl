# ruff: noqa: F401
from __future__ import annotations

from contextlib import contextmanager
import shutil
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.startup.startup_progress import ProjectSpinnerGroup
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.requirements.orchestrator import RequirementOutcome
from envctl_engine.startup.session import ProjectStartupResult
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.runtime.engine_runtime import ProjectContext
from envctl_engine.state.models import PortPlan
from envctl_engine.state.runtime_map import build_runtime_map


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class StartupSpinnerIntegrationTestCase(unittest.TestCase):
    pass


__all__ = [name for name in globals() if not name.startswith("__")]
