# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.ui.dashboard_rendering_parity_test_support import *


class DashboardRenderingLinksParityTests(DashboardRenderingParityTestCase):
    def test_dashboard_renders_service_log_on_single_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            log_path = Path(tmpdir) / "backend.log"
            log_path.write_text("ok\n", encoding="utf-8")
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                        log_path=str(log_path),
                    ),
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn(f"log: {log_path}", output)
            self.assertNotIn("log:\n", output)

    def test_dashboard_path_output_keeps_visible_text_and_adds_hyperlinks_when_forced(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            log_path = Path(tmpdir) / "backend.log"
            log_path.write_text("ok\n", encoding="utf-8")
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(
                load_config(self._config(repo, runtime)),
                env={"ENVCTL_UI_HYPERLINK_MODE": "on", "NO_COLOR": "1"},
            )
            summary = (
                engine.runtime_root
                / "runs"
                / "run-1"
                / "test-results"
                / "run_20260302_180000"
                / "Main"
                / "failed_tests_summary.txt"
            )
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_text("# Generated at: now\nNo failed tests.\n", encoding="utf-8")

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                        log_path=str(log_path),
                    ),
                },
                metadata={
                    "project_test_summaries": {
                        "Main": {
                            "summary_path": str(summary),
                            "status": "passed",
                        }
                    }
                },
            )

            buffer = _TtyStringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()
            visible = strip_ansi(output)
            expected_summary = summary_display_path(
                project_name="Main",
                entry=state.metadata["project_test_summaries"]["Main"],
            )

            self.assertIn("\x1b]8;;file://", output)
            self.assertIn(f"log: {log_path}", visible)
            self.assertIn(f"tests: {expected_summary}", visible)

    def test_dashboard_renders_project_test_summary_link_with_passed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            summary = (
                engine.runtime_root
                / "runs"
                / "run-1"
                / "test-results"
                / "run_20260302_180000"
                / "Main"
                / "failed_tests_summary.txt"
            )
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_text("# Generated at: now\nNo failed tests.\n", encoding="utf-8")

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={
                    "project_test_summaries": {
                        "Main": {
                            "summary_path": str(summary),
                            "status": "passed",
                        }
                    }
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()
            expected_short = engine.runtime_root / "runs" / "run-1" / f"ft_{hashlib.sha1(b'Main').hexdigest()[:10]}.txt"
            tests_line = next(line for line in output.splitlines() if "tests:" in line and str(expected_short) in line)

            self.assertIn("tests:", output)
            self.assertIn(str(expected_short), output)
            self.assertIn("✓ tests:", output)
            self.assertRegex(tests_line, rf"✓ tests: {re.escape(str(expected_short))} \([A-Z][a-z]{{2}} \d{{2}} \d{{2}}:\d{{2}}\)")
            self.assertTrue(expected_short.is_file())
            self.assertEqual(expected_short.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8"))
            self.assertNotIn(str(summary), output)

    def test_dashboard_renders_project_test_summary_link_with_failed_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            summary = (
                engine.runtime_root
                / "runs"
                / "run-1"
                / "test-results"
                / "run_20260302_180001"
                / "Main"
                / "failed_tests_summary.txt"
            )
            summary.parent.mkdir(parents=True, exist_ok=True)
            summary.write_text(
                (
                    "# Generated at: now\n"
                    "[Repository tests (unittest)]\n"
                    "- tests/test_auth.py::test_signup_regression\n"
                    "    AssertionError: expected 201, got 500\n"
                ),
                encoding="utf-8",
            )

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={
                    "project_test_summaries": {
                        "Main": {
                            "summary_path": str(summary),
                            "status": "failed",
                        }
                    }
                },
            )

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()
            expected_short = engine.runtime_root / "runs" / "run-1" / f"ft_{hashlib.sha1(b'Main').hexdigest()[:10]}.txt"
            tests_line = next(line for line in output.splitlines() if "tests:" in line and str(expected_short) in line)

            self.assertIn("tests:", output)
            self.assertIn(str(expected_short), output)
            self.assertIn("✗ tests:", output)
            self.assertRegex(tests_line, rf"✗ tests: {re.escape(str(expected_short))} \([A-Z][a-z]{{2}} \d{{2}} \d{{2}}:\d{{2}}\)")
            self.assertNotIn("tests/test_auth.py::test_signup_regression", output)
            self.assertNotIn("AssertionError: expected 201, got 500", output)
            self.assertTrue(expected_short.is_file())
            self.assertEqual(expected_short.read_text(encoding="utf-8"), summary.read_text(encoding="utf-8"))
            self.assertNotIn(str(summary), output)

    def test_dashboard_renders_active_project_pr_link(self) -> None:
        class _Runner:
            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = tuple(str(token) for token in cmd)
                if command == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="dev\n", stderr="")
                if command == ("git", "rev-parse", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
                if command[:4] == ("/usr/bin/gh", "pr", "list", "--head"):
                    return SimpleNamespace(
                        returncode=0,
                        stdout='[{"url":"https://github.com/example/supportopia/pull/123","state":"OPEN","mergedAt":null,"headRefOid":"abc123"}]\n',
                        stderr="",
                    )
                return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine.process_runner = _Runner()  # type: ignore[assignment]

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo / "frontend"),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(buffer):
                    engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("Main PR: https://github.com/example/supportopia/pull/123", output)

    def test_dashboard_renders_project_pr_link_in_gray_when_colors_enabled(self) -> None:
        class _Runner:
            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = tuple(str(token) for token in cmd)
                if command == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="dev\n", stderr="")
                if command == ("git", "rev-parse", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
                if command[:4] == ("/usr/bin/gh", "pr", "list", "--head"):
                    return SimpleNamespace(
                        returncode=0,
                        stdout='[{"url":"https://github.com/example/supportopia/pull/123","state":"OPEN","mergedAt":null,"headRefOid":"abc123"}]\n',
                        stderr="",
                    )
                return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={})
            engine._can_interactive_tty = lambda: True  # type: ignore[assignment]
            engine.process_runner = _Runner()  # type: ignore[assignment]

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo / "frontend"),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(buffer):
                    engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertIn("\x1b[90mhttps://github.com/example/supportopia/pull/123\x1b[0m", output)

    def test_dashboard_pr_lookup_uses_cache_when_metadata_missing(self) -> None:
        class _Runner:
            def __init__(self) -> None:
                self.calls: list[tuple[str, ...]] = []

            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = tuple(str(token) for token in cmd)
                self.calls.append(command)
                if command == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="feature/demo\n", stderr="")
                if command == ("git", "rev-parse", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
                if command[1:4] == ("pr", "list", "--head"):
                    return SimpleNamespace(
                        returncode=0,
                        stdout='[{"url":"https://github.com/example/supportopia/pull/999","state":"OPEN","mergedAt":null,"headRefOid":"abc123"}]\n',
                        stderr="",
                    )
                return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            runner = _Runner()
            engine.process_runner = runner  # type: ignore[assignment]

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo / "frontend"),
                        requested_port=9000,
                        actual_port=9000,
                        status="running",
                    ),
                },
                metadata={
                    "project_roots": {
                        "Main": str(repo),
                    }
                },
            )

            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(io.StringIO()):
                    engine._print_dashboard_snapshot(state)
                    engine._print_dashboard_snapshot(state)

            self.assertIn(("git", "rev-parse", "--abbrev-ref", "HEAD"), runner.calls)
            self.assertIn(("git", "rev-parse", "HEAD"), runner.calls)
            self.assertTrue(
                any(command[:4] == ("/usr/bin/gh", "pr", "list", "--head") for command in runner.calls),
                msg=runner.calls,
            )
            self.assertEqual(len(runner.calls), 5, msg=runner.calls)

    def test_dashboard_prefetches_project_pr_lookups_in_parallel(self) -> None:
        class _Runner:
            def __init__(self) -> None:
                self._lock = threading.Lock()
                self._active_gh = 0
                self.max_active_gh = 0

            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = env, timeout
                command = tuple(str(token) for token in cmd)
                if command == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="feature/demo\n", stderr="")
                if command == ("git", "rev-parse", "HEAD"):
                    name = Path(cwd).name if cwd is not None else "unknown"
                    return SimpleNamespace(returncode=0, stdout=f"{name}\n", stderr="")
                if command[:4] == ("/usr/bin/gh", "pr", "list", "--head"):
                    with self._lock:
                        self._active_gh += 1
                        self.max_active_gh = max(self.max_active_gh, self._active_gh)
                    time.sleep(0.05)
                    with self._lock:
                        self._active_gh -= 1
                    return SimpleNamespace(returncode=0, stdout="[]\n", stderr="")
                return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            for project_name in ("feature-a-1", "feature-b-1", "feature-c-1"):
                (repo / project_name / "backend").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            runner = _Runner()
            engine.process_runner = runner  # type: ignore[assignment]

            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo / "feature-a-1" / "backend"),
                        requested_port=8001,
                        actual_port=8001,
                        status="running",
                    ),
                    "feature-b-1 Backend": ServiceRecord(
                        name="feature-b-1 Backend",
                        type="backend",
                        cwd=str(repo / "feature-b-1" / "backend"),
                        requested_port=8002,
                        actual_port=8002,
                        status="running",
                    ),
                    "feature-c-1 Backend": ServiceRecord(
                        name="feature-c-1 Backend",
                        type="backend",
                        cwd=str(repo / "feature-c-1" / "backend"),
                        requested_port=8003,
                        actual_port=8003,
                        status="running",
                    ),
                },
                metadata={
                    "project_roots": {
                        "feature-a-1": str(repo / "feature-a-1"),
                        "feature-b-1": str(repo / "feature-b-1"),
                        "feature-c-1": str(repo / "feature-c-1"),
                    }
                },
            )

            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(io.StringIO()):
                    engine._print_dashboard_snapshot(state)

            self.assertGreaterEqual(runner.max_active_gh, 2)

    def test_dashboard_does_not_render_closed_project_pr(self) -> None:
        class _Runner:
            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = tuple(str(token) for token in cmd)
                if command == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="dev\n", stderr="")
                if command == ("git", "rev-parse", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="abc123\n", stderr="")
                if command[:4] == ("/usr/bin/gh", "pr", "list", "--head"):
                    return SimpleNamespace(
                        returncode=0,
                        stdout='[{"url":"https://github.com/example/supportopia/pull/123","state":"CLOSED","mergedAt":null,"headRefOid":"abc123"}]\n',
                        stderr="",
                    )
                return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine.process_runner = _Runner()  # type: ignore[assignment]

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            buffer = io.StringIO()
            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(buffer):
                    engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()

            self.assertNotIn("Main PR:", output)

    def test_dashboard_renders_merged_project_pr_only_when_head_matches(self) -> None:
        class _Runner:
            def __init__(self, *, head_oid: str) -> None:
                self.head_oid = head_oid

            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = tuple(str(token) for token in cmd)
                if command == ("git", "rev-parse", "--abbrev-ref", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout="dev\n", stderr="")
                if command == ("git", "rev-parse", "HEAD"):
                    return SimpleNamespace(returncode=0, stdout=f"{self.head_oid}\n", stderr="")
                if command[:4] == ("/usr/bin/gh", "pr", "list", "--head"):
                    return SimpleNamespace(
                        returncode=0,
                        stdout='[{"url":"https://github.com/example/supportopia/pull/123","state":"MERGED","mergedAt":"2026-03-10T14:29:43Z","headRefOid":"abc123"}]\n',
                        stderr="",
                    )
                return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)

            state = RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    ),
                },
                metadata={"project_roots": {"Main": str(repo)}},
            )

            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine.process_runner = _Runner(head_oid="abc123")  # type: ignore[assignment]
            buffer = io.StringIO()
            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(buffer):
                    engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()
            self.assertIn("Main PR: https://github.com/example/supportopia/pull/123 (merged)", output)

            engine = PythonEngineRuntime(load_config(self._config(repo, runtime)), env={"NO_COLOR": "1"})
            engine.process_runner = _Runner(head_oid="def456")  # type: ignore[assignment]
            buffer = io.StringIO()
            with patch("envctl_engine.ui.dashboard.rendering.shutil.which", return_value="/usr/bin/gh"):
                with redirect_stdout(buffer):
                    engine._print_dashboard_snapshot(state)
            output = buffer.getvalue()
            self.assertNotIn("Main PR:", output)
