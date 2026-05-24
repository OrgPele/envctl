from __future__ import annotations

import hashlib
import io
import json
import re
import threading
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import load_config
from envctl_engine.requirements.common import build_container_name
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.ui.dashboard.failure_detail_support import summary_display_path
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.dashboard.rendering import _dashboard_color_for_severity


class _TtyStringIO(io.StringIO):
    def isatty(self) -> bool:
        return True



class DashboardRenderingParityTestCase(unittest.TestCase):
    def _config(self, repo: Path, runtime: Path) -> dict[str, str]:
        return {
            "RUN_REPO_ROOT": str(repo),
            "RUN_SH_RUNTIME_DIR": str(runtime),
            "ENVCTL_DEFAULT_MODE": "main",
        }

    def _render_dashboard_for_active_frontend(
        self,
        configured_services: list[str],
        *,
        stopped_services: list[dict[str, str]] | None = None,
    ) -> tuple[str, list[tuple[str, dict[str, object]]]]:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine._reconcile_state_truth = lambda _state: []  # type: ignore[method-assign]
            emitted: list[tuple[str, dict[str, object]]] = []
            engine._emit = lambda event, **payload: emitted.append((event, payload))  # type: ignore[method-assign]

            metadata: dict[str, object] = {
                "project_roots": {"Main": str(repo)},
                "dashboard_project_configured_services": {"Main": configured_services},
            }
            if stopped_services is not None:
                metadata["dashboard_stopped_services"] = stopped_services
            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9000,
                        actual_port=9000,
                        pid=2222,
                        status="running",
                    ),
                },
                metadata=metadata,
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            return buffer.getvalue(), emitted

__all__ = [
    "Any",
    "DashboardRenderingParityTestCase",
    "Path",
    "PYTHON_ROOT",
    "PythonEngineRuntime",
    "REPO_ROOT",
    "RequirementsResult",
    "RunState",
    "ServiceRecord",
    "SimpleNamespace",
    "_TtyStringIO",
    "_dashboard_color_for_severity",
    "build_container_name",
    "build_runtime_map",
    "cast",
    "hashlib",
    "io",
    "json",
    "load_config",
    "patch",
    "re",
    "redirect_stdout",
    "strip_ansi",
    "summary_display_path",
    "tempfile",
    "threading",
    "time",
    "unittest",
]
