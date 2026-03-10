from __future__ import annotations

import os
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import RunState, ServiceRecord


class DashboardRenderAlignmentTests(unittest.TestCase):
    def _runtime(self, repo: Path, runtime: Path) -> PythonEngineRuntime:
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
            }
        )
        return PythonEngineRuntime(config, env={})

    def test_dashboard_truncates_long_project_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = self._runtime(repo, runtime)
            engine._terminal_size = lambda: (64, 24)  # type: ignore[assignment]

            project = "very-long-project-name-that-should-be-truncated-for-dashboard-output"
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    f"{project} Backend": ServiceRecord(
                        name=f"{project} Backend",
                        type="backend",
                        cwd="/tmp",
                        pid=123,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    f"{project} Frontend": ServiceRecord(
                        name=f"{project} Frontend",
                        type="frontend",
                        cwd="/tmp",
                        pid=456,
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
            )

            out = StringIO()
            with redirect_stdout(out):
                engine._print_dashboard_snapshot(state)

            rendered = out.getvalue()
            self.assertIn("...", rendered)

    def test_dashboard_respects_no_color(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = self._runtime(repo, runtime)
            state = RunState(run_id="run-1", mode="main")

            out = StringIO()
            prior = os.environ.get("NO_COLOR")
            os.environ["NO_COLOR"] = "1"
            try:
                with redirect_stdout(out):
                    engine._print_dashboard_snapshot(state)
            finally:
                if prior is None:
                    os.environ.pop("NO_COLOR", None)
                else:
                    os.environ["NO_COLOR"] = prior

            self.assertNotIn("\x1b[", out.getvalue())


if __name__ == "__main__":
    unittest.main()
