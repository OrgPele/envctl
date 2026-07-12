from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile
import unittest

from envctl_engine.state.action_log_support import StateActionLogSupport
from envctl_engine.state.models import RunState, ServiceRecord


class StateActionLogSupportTests(unittest.TestCase):
    def test_logs_payload_reads_tail_and_normalizes_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "backend.log"
            log_path.write_text("one\n\033[31mtwo\033[0m\nthree\n", encoding="utf-8")
            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=tmp,
                        log_path=str(log_path),
                        status="running",
                    )
                },
            )
            support = StateActionLogSupport(
                normalize_log_line=lambda line, no_color: line.replace("\033[31m", "").replace("\033[0m", "")
                if no_color
                else line
            )

            payload = support.logs_payload(state=state, tail=2, follow=True, duration_seconds=3.0, no_color=True)

        self.assertEqual(payload["run_id"], "run-1")
        self.assertEqual(payload["follow_requested"], True)
        self.assertEqual(payload["duration_seconds"], 3.0)
        self.assertEqual(payload["services"][0]["tail_lines"], ["two", "three"])

    def test_service_log_issues_detects_recent_problem_lines_with_ansi_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "backend.log"
            log_path.write_text("ok\n\033[31mERROR\033[0m failed import\nwarning: deprecated\n", encoding="utf-8")
            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=tmp,
                        log_path=str(log_path),
                        status="failed",
                    )
                },
            )
            support = StateActionLogSupport(normalize_log_line=lambda line, _no_color: line)

            issues = support.service_log_issues(state, max_matches=1)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["service"], "Main Backend")
        self.assertEqual(issues[0]["lines"], ["warning: deprecated"])
        self.assertTrue(StateActionLogSupport.log_line_has_issue("\033[31mTraceback\033[0m"))

    def test_clear_service_logs_truncates_available_files_and_reports_missing_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "backend.log"
            missing_path = Path(tmp) / "missing.log"
            log_path.write_text("old\n", encoding="utf-8")
            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=tmp,
                        log_path=str(log_path),
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=tmp,
                        log_path=str(missing_path),
                    ),
                    "Main Worker": ServiceRecord(name="Main Worker", type="worker", cwd=tmp),
                },
            )

            output = StringIO()
            with redirect_stdout(output):
                summary = StateActionLogSupport.clear_service_logs(state)

            self.assertEqual(summary, (1, 1, 1, 0))
            self.assertEqual(log_path.read_text(encoding="utf-8"), "")
            rendered = output.getvalue()
            self.assertIn("Main Backend: log cleared", rendered)
            self.assertIn("Main Frontend: log missing", rendered)
            self.assertIn("Main Worker: log=n/a", rendered)

    def test_clear_service_logs_advances_docker_cursor_without_snapshot_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "docker-backend.log"
            marker = Path(f"{log_path}.docker-since")
            state = RunState(
                run_id="run-docker",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=tmp,
                        log_path=str(log_path),
                        runtime_kind="docker",
                    )
                },
            )

            summary = StateActionLogSupport.clear_service_logs(state, quiet=True)

            self.assertEqual(summary, (1, 0, 0, 0))
            self.assertFalse(log_path.exists())
            self.assertTrue(marker.is_file())


if __name__ == "__main__":
    unittest.main()
