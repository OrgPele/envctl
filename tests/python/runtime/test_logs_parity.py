from __future__ import annotations

import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.state import dump_state


class LogsParityTests(unittest.TestCase):
    def _write_state(self, repo: Path, runtime: Path, log_path: Path) -> PythonEngineRuntime:
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
            }
        )
        runtime_obj = PythonEngineRuntime(config, env={})
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=str(repo),
                    pid=9999,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                    log_path=str(log_path),
                )
            },
        )
        dump_state(state, str(runtime / "python-engine" / "run_state.json"))
        return runtime_obj

    def test_logs_tail_respects_logs_tail_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            log_path = root / "backend.log"
            log_path.write_text("line-1\nline-2\nline-3\n", encoding="utf-8")
            runtime_obj = self._write_state(repo, runtime, log_path)

            out = StringIO()
            with redirect_stdout(out):
                code = runtime_obj.dispatch(parse_route(["logs", "--all", "--logs-tail", "2"], env={}))

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("line-2", rendered)
            self.assertIn("line-3", rendered)
            self.assertNotIn("line-1", rendered)

    def test_logs_follow_with_duration_streams_new_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            log_path = root / "backend.log"
            log_path.write_text("boot\n", encoding="utf-8")
            runtime_obj = self._write_state(repo, runtime, log_path)

            def append_line() -> None:
                time.sleep(0.2)
                with log_path.open("a", encoding="utf-8") as handle:
                    handle.write("follow-line\n")

            writer = threading.Thread(target=append_line, daemon=True)
            writer.start()

            out = StringIO()
            with redirect_stdout(out):
                code = runtime_obj.dispatch(
                    parse_route(["logs", "--all", "--logs-tail", "0", "--logs-follow", "--logs-duration", "1"], env={})
                )
            writer.join(timeout=1.0)

            self.assertEqual(code, 0)
            self.assertIn("follow-line", out.getvalue())

    def test_logs_no_color_strips_ansi_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            log_path = root / "backend.log"
            log_path.write_text("\x1b[31merror\x1b[0m plain\n", encoding="utf-8")
            runtime_obj = self._write_state(repo, runtime, log_path)

            out = StringIO()
            with redirect_stdout(out):
                code = runtime_obj.dispatch(parse_route(["logs", "--all", "--logs-no-color"], env={}))

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("error plain", rendered)
            self.assertNotIn("\x1b[31m", rendered)

    def test_logs_does_not_require_state_truth_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            log_path = root / "backend.log"
            log_path.write_text("line\n", encoding="utf-8")
            runtime_obj = self._write_state(repo, runtime, log_path)

            def _unexpected(*args: object, **kwargs: object) -> object:
                raise AssertionError("logs should not reconcile runtime truth")

            runtime_obj._reconcile_state_truth = _unexpected  # type: ignore[method-assign]
            runtime_obj._requirement_truth_issues = _unexpected  # type: ignore[method-assign]
            runtime_obj._recent_failure_messages = _unexpected  # type: ignore[method-assign]

            out = StringIO()
            with redirect_stdout(out):
                code = runtime_obj.dispatch(parse_route(["logs", "--all", "--logs-tail", "1"], env={}))

            self.assertEqual(code, 0)
            self.assertIn("line", out.getvalue())

    def test_logs_requires_explicit_target_when_non_interactive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            log_path = root / "backend.log"
            log_path.write_text("line\n", encoding="utf-8")
            runtime_obj = self._write_state(repo, runtime, log_path)

            out = StringIO()
            with redirect_stdout(out):
                code = runtime_obj.dispatch(parse_route(["logs"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("No log target selected.", out.getvalue())


if __name__ == "__main__":
    unittest.main()
