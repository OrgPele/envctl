# ruff: noqa: F401,F811
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.planning.plan_agent_launch_support import PlanSelectionResult
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.spinner_service import SpinnerPolicy


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class PlanningWorktreeSetupTestCase(unittest.TestCase):
    def _runtime(self, repo: Path, runtime: Path, *, env: dict[str, str] | None = None) -> PythonEngineRuntime:
        resolved_env = dict(env or {})
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
                **resolved_env,
            }
        )
        return PythonEngineRuntime(config, env=resolved_env)

    def _read_provenance(self, worktree_root: Path) -> dict[str, object]:
        path = worktree_root / ".envctl-state" / "worktree-provenance.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _worktree_add_index(self, command: list[str]) -> int:
        try:
            index = command.index("worktree")
        except ValueError as exc:
            raise AssertionError(f"not a worktree command: {command}") from exc
        self.assertLess(index + 1, len(command))
        self.assertEqual(command[index + 1], "add")
        return index

    def _assert_hooks_disabled_for_worktree_add(self, command: list[str]) -> None:
        c_index = command.index("-C")
        self.assertEqual(command[c_index - 2 : c_index], ["-c", "core.hooksPath=/dev/null"])

    def _assert_hooks_inherited_for_worktree_add(self, command: list[str]) -> None:
        self.assertNotIn("core.hooksPath=/dev/null", command)


__all__ = [name for name in globals() if not name.startswith("__")]
