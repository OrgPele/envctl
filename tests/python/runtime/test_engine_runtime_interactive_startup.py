from __future__ import annotations

import os
import re
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
    _FakeProcessRunner,
)


class EngineRuntimeInteractiveStartupTests(_EngineRuntimeRealStartupTestCase):
    def test_start_enters_interactive_dashboard_loop_in_tty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a"], env={})

            with (
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 1)

    def test_start_skips_interactive_dashboard_loop_in_batch_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            with (
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 0)

    def test_start_skips_interactive_dashboard_loop_when_term_is_dumb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a"], env={})

            with (
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "dumb"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 0)

    def test_dashboard_defaults_to_interactive_in_tty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--dashboard"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 1)

    def test_dashboard_non_interactive_flag_skips_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
            )

            route = parse_route(["--dashboard", "--non-interactive"], env={})
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch.dict(os.environ, {"TERM": "xterm-256color"}, clear=False),
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as loop_mock,
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(loop_mock.call_count, 0)

    def test_interactive_command_start_suppresses_loading_progress_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]

            route = parse_route(["--plan", "feature-a"], env={})
            route.flags = {**route.flags, "interactive_command": True, "batch": True}

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            output = out.getvalue()
            self.assertNotIn("Starting project feature-a-1", output)
            self.assertNotIn("Requirements ready for feature-a-1", output)
            self.assertNotIn("Services ready for feature-a-1", output)
            self.assertNotIn("envctl Python engine run summary", output)

    def test_dashboard_snapshot_uses_grouped_shell_like_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo / "trees" / "feature-a" / "1" / "backend"),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        log_path="/tmp/backend.log",
                        status="running",
                    ),
                    "feature-a-1 Frontend": ServiceRecord(
                        name="feature-a-1 Frontend",
                        type="frontend",
                        cwd=str(repo / "trees" / "feature-a" / "1" / "frontend"),
                        pid=2222,
                        requested_port=9000,
                        actual_port=9002,
                        log_path="/tmp/frontend.log",
                        status="running",
                    ),
                },
                requirements={
                    "feature-a-1": RequirementsResult(
                        project="feature-a-1",
                        n8n={"enabled": True, "success": True, "final": 5678},
                        health="healthy",
                    )
                },
            )

            out = StringIO()
            with (
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                redirect_stdout(out),
            ):
                engine._print_dashboard_snapshot(state)

            plain = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", out.getvalue())
            self.assertIn("Development Environment - Interactive Mode", plain)
            self.assertIn("Running Services:", plain)
            self.assertIn("feature-a-1", plain)
            self.assertIn("Backend: http://localhost:8000 (PID: 1111)", plain)
            self.assertIn("Frontend: http://localhost:9002 (PID: 2222)", plain)
            self.assertIn("log: /tmp/backend.log", plain)
            self.assertIn("log: /tmp/frontend.log", plain)
            self.assertIn("n8n: http://localhost:5678 [Healthy]", plain)

    def test_run_planning_selection_menu_flushes_pending_input_before_raw_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})

            planning_files = ["backend/task-a.md"]
            selected_counts = {"backend/task-a.md": 1}
            existing_counts = {"backend/task-a.md": 0}

            with (
                patch.object(engine, "_flush_pending_interactive_input") as flush_mock,
                patch(
                    "envctl_engine.planning.worktree_domain.select_planning_counts_textual",
                    return_value={"backend/task-a.md": 1},
                ) as selector_mock,
                redirect_stdout(StringIO()),
            ):
                chosen = engine._run_planning_selection_menu(
                    planning_files=planning_files,
                    selected_counts=selected_counts,
                    existing_counts=existing_counts,
                )

            self.assertEqual(chosen, {"backend/task-a.md": 1})
            self.assertEqual(flush_mock.call_count, 1)
            selector_mock.assert_called_once()

    def test_interactive_command_ignores_escape_only_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("\x1b[A", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, [])

    def test_interactive_loop_flushes_pending_input_after_noise_only_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            commands_seen: list[str] = []

            def fake_run_interactive(raw: str, current: RunState) -> tuple[bool, RunState]:
                commands_seen.append(raw)
                return False, current

            with (
                patch.object(engine, "_can_interactive_tty", return_value=True),
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_print_dashboard_snapshot"),
                patch.object(engine, "_read_interactive_command_line", side_effect=["\x1b[A", "q"]),
                patch.object(engine, "_run_interactive_command", side_effect=fake_run_interactive),
                patch.object(engine, "_flush_pending_interactive_input") as flush_mock,
                redirect_stdout(StringIO()),
            ):
                code = engine._run_interactive_dashboard_loop(state)

            self.assertEqual(code, 0)
            self.assertEqual(commands_seen, ["q"])
            self.assertEqual(flush_mock.call_count, 2)

    def test_interactive_loop_flushes_pending_input_after_partial_csi_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            commands_seen: list[str] = []

            def fake_run_interactive(raw: str, current: RunState) -> tuple[bool, RunState]:
                commands_seen.append(raw)
                return False, current

            with (
                patch.object(engine, "_can_interactive_tty", return_value=True),
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_print_dashboard_snapshot"),
                patch.object(engine, "_read_interactive_command_line", side_effect=["[A", "q"]),
                patch.object(engine, "_run_interactive_command", side_effect=fake_run_interactive),
                patch.object(engine, "_flush_pending_interactive_input") as flush_mock,
                redirect_stdout(StringIO()),
            ):
                code = engine._run_interactive_dashboard_loop(state)

            self.assertEqual(code, 0)
            self.assertEqual(commands_seen, ["q"])
            self.assertEqual(flush_mock.call_count, 2)

    def test_interactive_loop_flushes_pending_input_after_bracketed_paste_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            commands_seen: list[str] = []

            def fake_run_interactive(raw: str, current: RunState) -> tuple[bool, RunState]:
                commands_seen.append(raw)
                return False, current

            with (
                patch.object(engine, "_can_interactive_tty", return_value=True),
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_print_dashboard_snapshot"),
                patch.object(engine, "_read_interactive_command_line", side_effect=["[200~", "q"]),
                patch.object(engine, "_run_interactive_command", side_effect=fake_run_interactive),
                patch.object(engine, "_flush_pending_interactive_input") as flush_mock,
                redirect_stdout(StringIO()),
            ):
                code = engine._run_interactive_dashboard_loop(state)

            self.assertEqual(code, 0)
            self.assertEqual(commands_seen, ["q"])
            self.assertEqual(flush_mock.call_count, 2)

    def test_interactive_loop_does_not_flush_before_each_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            commands_seen: list[str] = []

            def fake_run_interactive(raw: str, current: RunState) -> tuple[bool, RunState]:
                commands_seen.append(raw)
                if raw == "q":
                    return False, current
                return True, current

            with (
                patch.object(engine, "_can_interactive_tty", return_value=True),
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_print_dashboard_snapshot"),
                patch.object(engine, "_read_interactive_command_line", side_effect=["help", "q"]),
                patch.object(engine, "_run_interactive_command", side_effect=fake_run_interactive),
                patch.object(engine, "_flush_pending_interactive_input") as flush_mock,
                redirect_stdout(StringIO()),
            ):
                code = engine._run_interactive_dashboard_loop(state)

            self.assertEqual(code, 0)
            self.assertEqual(commands_seen, ["help", "q"])
            self.assertEqual(flush_mock.call_count, 1)

    def test_interactive_loop_flushes_pending_input_after_empty_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            commands_seen: list[str] = []

            def fake_run_interactive(raw: str, current: RunState) -> tuple[bool, RunState]:
                commands_seen.append(raw)
                return False, current

            with (
                patch.object(engine, "_can_interactive_tty", return_value=True),
                patch.object(engine, "_try_load_existing_state", return_value=state),
                patch.object(engine, "_print_dashboard_snapshot"),
                patch.object(engine, "_read_interactive_command_line", side_effect=["", "q"]),
                patch.object(engine, "_run_interactive_command", side_effect=fake_run_interactive),
                patch.object(engine, "_flush_pending_interactive_input") as flush_mock,
                redirect_stdout(StringIO()),
            ):
                code = engine._run_interactive_dashboard_loop(state)

            self.assertEqual(code, 0)
            self.assertEqual(commands_seen, ["q"])
            self.assertEqual(flush_mock.call_count, 2)

    def test_interactive_command_strips_escape_prefix_before_alias_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("\x1b[As", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, ["stop"])

    def test_interactive_command_strips_partial_csi_prefix_before_alias_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("[As", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, ["stop"])

    def test_interactive_command_ignores_partial_csi_only_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("[A", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, [])

    def test_interactive_command_strips_bracket_fragment_before_alias_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("[s", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, ["stop"])

    def test_interactive_command_strips_ss3_escape_prefix_before_alias_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("\x1bOAs", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, ["stop"])

    def test_interactive_command_ignores_partial_ss3_only_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with patch.object(engine, "_try_load_existing_state", return_value=state):
                should_continue, next_state = engine._run_interactive_command("OA", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, [])

    def test_interactive_command_ignores_bracketed_paste_fragment_without_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            state = RunState(run_id="run-1", mode="trees", services={})

            dispatch_calls: list[str] = []

            def fake_dispatch(route):  # noqa: ANN001
                dispatch_calls.append(route.command)
                return 0

            engine.dispatch = fake_dispatch  # type: ignore[method-assign]
            with (
                patch.object(engine, "_try_load_existing_state", return_value=state),
                redirect_stdout(StringIO()) as buffer,
            ):
                should_continue, next_state = engine._run_interactive_command("[200~", state)

            self.assertTrue(should_continue)
            self.assertIs(next_state, state)
            self.assertEqual(dispatch_calls, [])
            self.assertEqual(buffer.getvalue(), "")

