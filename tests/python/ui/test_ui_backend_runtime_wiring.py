from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import RunState


class _BackendStub:
    def __init__(self) -> None:
        self.calls = 0

    def run_dashboard_loop(self, *, state: RunState, runtime: object) -> int:  # noqa: ARG002
        self.calls += 1
        return 7


class UiBackendRuntimeWiringTests(unittest.TestCase):
    def test_runtime_dashboard_loop_delegates_to_selected_backend(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            backend = _BackendStub()
            engine.ui_backend = backend  # type: ignore[attr-defined]

            code = engine._run_interactive_dashboard_loop(RunState(run_id="run-1", mode="main"))

            self.assertEqual(code, 7)
            self.assertEqual(backend.calls, 1)

