from __future__ import annotations

from contextlib import contextmanager, redirect_stdout
from io import StringIO
import importlib
import unittest
from typing import Any, cast
from unittest.mock import patch

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
models_module = importlib.import_module("envctl_engine.state.models")
command_loop_module = importlib.import_module("envctl_engine.ui.command_loop")

RunState = models_module.RunState
run_dashboard_command_loop = command_loop_module.run_dashboard_command_loop


class _RuntimeStub:
    def __init__(self, state: RunState) -> None:
        self._state = state
        self.env: dict[str, str] = {}
        self.events: list[dict[str, object]] = []

    def _try_load_existing_state(self, *, mode: str, strict_mode_match: bool = True):  # noqa: ANN001, ARG002
        return self._state

    @staticmethod
    def _print_dashboard_snapshot(_state: RunState) -> None:
        return None

    def _emit(self, event_name: str, **payload: object):  # noqa: ANN001
        self.events.append({"event": event_name, **payload})
        return None


class DashboardLoopTests(unittest.TestCase):
    def test_dashboard_loop_does_not_force_basic_input_backend_for_command_prompt(self) -> None:
        state = RunState(run_id="run-0", mode="trees")
        runtime = _RuntimeStub(state)
        prefer_flags: list[bool] = []

        class _SessionStub:
            def __init__(
                self,
                _env,
                *,
                input_provider=None,
                prefer_basic_input=False,
                emit=None,
                debug_recorder=None,
            ):  # noqa: ANN001
                prefer_flags.append(bool(prefer_basic_input))
                self._input_provider = input_provider or (lambda _prompt: "q")
                _ = emit
                _ = debug_recorder

            def read_command_line(self, _prompt: str) -> str:
                return "q"

        def handle_command(_raw: str, current: RunState, _rt: object):  # noqa: ANN001
            return False, current

        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.command_loop.TerminalSession", _SessionStub),
        ):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
            )

        self.assertEqual(code, 0)
        self.assertEqual(prefer_flags, [False])

    def test_dashboard_loop_exits_on_quit(self) -> None:
        state = RunState(run_id="run-1", mode="trees")
        runtime = _RuntimeStub(state)

        def handle_command(_raw: str, current: RunState, _rt: object):  # noqa: ANN001
            return False, current

        with patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
                input_provider=lambda _prompt: "q",
            )

        self.assertEqual(code, 0)

    def test_dashboard_loop_restores_terminal_on_exit(self) -> None:
        state = RunState(run_id="run-1b", mode="trees")
        runtime = _RuntimeStub(state)

        def handle_command(_raw: str, current: RunState, _rt: object):  # noqa: ANN001
            return False, current

        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.command_loop._restore_stdin_terminal_sane") as restore_mock,
        ):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
                input_provider=lambda _prompt: "q",
            )

        self.assertEqual(code, 0)
        restore_mock.assert_called_once()

    def test_dashboard_loop_does_not_print_running_command_spinner(self) -> None:
        state = RunState(run_id="run-2", mode="trees")
        runtime = _RuntimeStub(state)

        def handle_command(_raw: str, current: RunState, _rt: object):  # noqa: ANN001
            return False, current

        out = StringIO()
        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            redirect_stdout(out),
        ):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
                input_provider=lambda _prompt: "q",
            )

        self.assertEqual(code, 0)
        self.assertNotIn("Running command...", out.getvalue())

    def test_dashboard_loop_updates_spinner_status_from_runtime_events(self) -> None:
        state = RunState(run_id="run-3", mode="trees")
        runtime = _RuntimeStub(state)

        spinner_calls: list[tuple[str, str, bool] | tuple[str, str]] = []

        class _SpinnerStub:
            def start(self) -> None:
                spinner_calls.append(("spin-start", ""))

            def update(self, message: str) -> None:
                spinner_calls.append(("update", message))

            def succeed(self, message: str) -> None:
                spinner_calls.append(("succeed", message))

            def fail(self, message: str) -> None:
                spinner_calls.append(("fail", message))

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            spinner_calls.append(("start", message, enabled))
            yield _SpinnerStub()

        def handle_command(_raw: str, current: RunState, rt: object):  # noqa: ANN001
            runtime_any = cast(Any, rt)
            runtime_any._emit("command.route.selected", command="test")
            runtime_any._emit("action.command.start", command="test")
            runtime_any._emit("action.command.finish", command="test", code=0)
            return False, current

        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.command_loop.spinner", side_effect=fake_spinner),
            patch("envctl_engine.ui.command_loop.spinner_enabled", return_value=True),
        ):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
                input_provider=lambda _prompt: "t",
            )

        self.assertEqual(code, 0)
        self.assertIn(("start", "Preparing tests...", True), spinner_calls)
        self.assertIn(("spin-start", ""), spinner_calls)
        self.assertIn(("update", "Running test..."), spinner_calls)
        self.assertIn(("succeed", "Command finished; leaving interactive mode..."), spinner_calls)
        self.assertNotIn(("update", "Routing test command..."), spinner_calls)

    def test_dashboard_loop_hides_irrelevant_sections_when_commands_are_disabled(self) -> None:
        state = RunState(
            run_id="run-plan",
            mode="trees",
            metadata={
                "dashboard_hidden_commands": [
                    "stop",
                    "restart",
                    "stop-all",
                    "blast-all",
                    "logs",
                    "clear-logs",
                    "health",
                    "errors",
                ]
            },
        )
        runtime = _RuntimeStub(state)

        def handle_command(_raw: str, current: RunState, _rt: object):  # noqa: ANN001
            return False, current

        out = StringIO()
        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            redirect_stdout(out),
        ):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
                input_provider=lambda _prompt: "q",
            )

        self.assertEqual(code, 0)
        rendered = out.getvalue()
        self.assertIn("(q)uit", rendered)
        self.assertNotIn("Lifecycle:", rendered)
        self.assertIn("Actions:", rendered)
        self.assertNotIn("Inspect:", rendered)
        self.assertNotIn("(m)igrate", rendered)
        self.assertNotIn("(l)ogs", rendered)
        self.assertNotIn("confi(g)", rendered)

    def test_dashboard_loop_marks_spinner_failed_from_action_finish_event(self) -> None:
        state = RunState(run_id="run-4", mode="trees")
        runtime = _RuntimeStub(state)

        spinner_calls: list[tuple[str, str, bool] | tuple[str, str]] = []

        class _SpinnerStub:
            def start(self) -> None:
                spinner_calls.append(("spin-start", ""))

            def update(self, message: str) -> None:
                spinner_calls.append(("update", message))

            def succeed(self, message: str) -> None:
                spinner_calls.append(("succeed", message))

            def fail(self, message: str) -> None:
                spinner_calls.append(("fail", message))

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            spinner_calls.append(("start", message, enabled))
            yield _SpinnerStub()

        def handle_command(_raw: str, current: RunState, rt: object):  # noqa: ANN001
            runtime_any = cast(Any, rt)
            runtime_any._emit("action.command.start", command="test")
            runtime_any._emit("action.command.finish", command="test", code=2)
            return False, current

        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.command_loop.spinner", side_effect=fake_spinner),
            patch("envctl_engine.ui.command_loop.spinner_enabled", return_value=True),
        ):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
                input_provider=lambda _prompt: "t",
            )

        self.assertEqual(code, 0)
        self.assertIn(("spin-start", ""), spinner_calls)
        self.assertIn(("update", "test failed (exit 2)"), spinner_calls)
        self.assertIn(("fail", "test failed (exit 2)"), spinner_calls)

    def test_dashboard_loop_consumes_return_prompt_after_spinner_finishes(self) -> None:
        state = RunState(run_id="run-4b", mode="trees")
        runtime = _RuntimeStub(state)

        events: list[str] = []

        class _SpinnerStub:
            def start(self) -> None:
                events.append("spinner-start")

            def update(self, message: str) -> None:
                events.append(f"spinner-update:{message}")

            def succeed(self, message: str) -> None:
                events.append(f"spinner-succeed:{message}")

            def fail(self, message: str) -> None:
                events.append(f"spinner-fail:{message}")

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = start_immediately
            events.append(f"spinner-created:{message}:{enabled}")
            yield _SpinnerStub()

        responses = iter(["t", "", "q"])

        def read_command_line(prompt: str) -> str:
            events.append(f"prompt:{prompt}")
            return next(responses)

        def handle_command(raw: str, current: RunState, rt: object):  # noqa: ANN001
            if raw == "q":
                return False, current
            runtime_any = cast(Any, rt)
            runtime_any._emit("action.command.start", command="test")
            runtime_any._emit("action.command.finish", command="test", code=1)
            setattr(runtime_any, "_dashboard_return_prompt", "Press Enter to return to dashboard: ")
            return True, current

        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.command_loop.spinner", side_effect=fake_spinner),
            patch("envctl_engine.ui.command_loop.spinner_enabled", return_value=True),
        ):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
                read_command_line=read_command_line,
            )

        self.assertEqual(code, 0)
        self.assertLess(
            events.index("spinner-fail:test failed (exit 1)"),
            events.index("prompt:Press Enter to return to dashboard:"),
        )

    def test_dashboard_loop_does_not_start_spinner_for_route_selection_only(self) -> None:
        state = RunState(run_id="run-5", mode="trees")
        runtime = _RuntimeStub(state)

        spinner_calls: list[tuple[str, str, bool] | tuple[str, str]] = []

        class _SpinnerStub:
            def start(self) -> None:
                spinner_calls.append(("spin-start", ""))

            def update(self, message: str) -> None:
                spinner_calls.append(("update", message))

            def succeed(self, message: str) -> None:
                spinner_calls.append(("succeed", message))

            def fail(self, message: str) -> None:
                spinner_calls.append(("fail", message))

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            spinner_calls.append(("start", message, enabled))
            yield _SpinnerStub()

        def handle_command(_raw: str, current: RunState, rt: object):  # noqa: ANN001
            runtime_any = cast(Any, rt)
            runtime_any._emit("command.route.selected", command="test")
            return False, current

        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.command_loop.spinner", side_effect=fake_spinner),
            patch("envctl_engine.ui.command_loop.spinner_enabled", return_value=True),
        ):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
                input_provider=lambda _prompt: "t",
            )

        self.assertEqual(code, 0)
        self.assertIn(("start", "Preparing tests...", True), spinner_calls)
        self.assertNotIn(("spin-start", ""), spinner_calls)
        self.assertNotIn(("update", "Routing test command..."), spinner_calls)
        self.assertNotIn(("succeed", "Command finished; leaving interactive mode..."), spinner_calls)

    def test_dashboard_loop_uses_ui_status_event_for_precise_spinner_updates(self) -> None:
        state = RunState(run_id="run-6", mode="trees")
        runtime = _RuntimeStub(state)

        spinner_calls: list[tuple[str, str, bool] | tuple[str, str]] = []

        class _SpinnerStub:
            def start(self) -> None:
                spinner_calls.append(("spin-start", ""))

            def update(self, message: str) -> None:
                spinner_calls.append(("update", message))

            def succeed(self, message: str) -> None:
                spinner_calls.append(("succeed", message))

            def fail(self, message: str) -> None:
                spinner_calls.append(("fail", message))

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = start_immediately
            spinner_calls.append(("start", message, enabled))
            yield _SpinnerStub()

        def handle_command(_raw: str, current: RunState, rt: object):  # noqa: ANN001
            runtime_any = cast(Any, rt)
            runtime_any._emit("action.command.start", command="restart")
            runtime_any._emit("ui.status", message="Starting backend for Main on port 8000...")
            runtime_any._emit("action.command.finish", command="restart", code=0)
            return False, current

        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.command_loop.spinner", side_effect=fake_spinner),
            patch("envctl_engine.ui.command_loop.spinner_enabled", return_value=True),
        ):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
                input_provider=lambda _prompt: "r",
            )

        self.assertEqual(code, 0)
        self.assertIn(("spin-start", ""), spinner_calls)
        self.assertIn(("update", "Starting backend for Main on port 8000..."), spinner_calls)
        self.assertIn(("succeed", "Command finished; leaving interactive mode..."), spinner_calls)

    def test_dashboard_loop_does_not_emit_pr_complete_spinner_footer(self) -> None:
        state = RunState(run_id="run-pr-no-footer", mode="trees")
        runtime = _RuntimeStub(state)

        spinner_calls: list[tuple[str, str, bool] | tuple[str, str]] = []

        class _SpinnerStub:
            def start(self) -> None:
                spinner_calls.append(("spin-start", ""))

            def update(self, message: str) -> None:
                spinner_calls.append(("update", message))

            def succeed(self, message: str) -> None:
                spinner_calls.append(("succeed", message))

            def fail(self, message: str) -> None:
                spinner_calls.append(("fail", message))

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = start_immediately
            spinner_calls.append(("start", message, enabled))
            yield _SpinnerStub()

        call_count = {"n": 0}

        def input_provider(_prompt: str) -> str:
            call_count["n"] += 1
            return "p" if call_count["n"] == 1 else "q"

        def handle_command(raw: str, current: RunState, rt: object):  # noqa: ANN001
            runtime_any = cast(Any, rt)
            normalized = raw.strip().lower()
            if normalized.startswith("p"):
                runtime_any._emit("action.command.start", command="pr")
                runtime_any._emit(
                    "ui.status", message="PR already exists: https://github.com/kfiramar/supportopia/pull/53"
                )
                runtime_any._emit("action.command.finish", command="pr", code=0)
                return True, current
            return False, current

        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.command_loop.spinner", side_effect=fake_spinner),
            patch("envctl_engine.ui.command_loop.spinner_enabled", return_value=True),
        ):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
                input_provider=input_provider,
            )

        self.assertEqual(code, 0)
        self.assertIn(("start", "Preparing pull request workflow...", True), spinner_calls)
        self.assertIn(("spin-start", ""), spinner_calls)
        self.assertIn(("update", "PR already exists: https://github.com/kfiramar/supportopia/pull/53"), spinner_calls)
        self.assertNotIn(("succeed", "pr complete"), spinner_calls)

    def test_dashboard_loop_suppresses_command_spinner_when_suite_group_spinner_is_enabled(self) -> None:
        state = RunState(run_id="run-6b", mode="trees")
        runtime = _RuntimeStub(state)

        spinner_calls: list[tuple[str, str, bool] | tuple[str, str]] = []

        class _SpinnerStub:
            def start(self) -> None:
                spinner_calls.append(("spin-start", ""))

            def update(self, message: str) -> None:
                spinner_calls.append(("update", message))

            def succeed(self, message: str) -> None:
                spinner_calls.append(("succeed", message))

            def fail(self, message: str) -> None:
                spinner_calls.append(("fail", message))

            def end(self) -> None:
                spinner_calls.append(("end", ""))

        @contextmanager
        def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
            _ = start_immediately
            spinner_calls.append(("start", message, enabled))
            yield _SpinnerStub()

        def handle_command(_raw: str, current: RunState, rt: object):  # noqa: ANN001
            runtime_any = cast(Any, rt)
            runtime_any._emit("action.command.start", command="test")
            runtime_any._emit("ui.status", message="Running tests for 3 selected projects...")
            runtime_any._emit("test.suite_spinner_group.policy", enabled=True, reason="enabled")
            runtime_any._emit("ui.status", message="This should not update command-loop spinner")
            runtime_any._emit("action.command.finish", command="test", code=0)
            return False, current

        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch("envctl_engine.ui.command_loop.spinner", side_effect=fake_spinner),
            patch("envctl_engine.ui.command_loop.spinner_enabled", return_value=True),
        ):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
                input_provider=lambda _prompt: "t",
            )

        self.assertEqual(code, 0)
        self.assertIn(("spin-start", ""), spinner_calls)
        self.assertIn(("update", "Running tests for 3 selected projects..."), spinner_calls)
        self.assertIn(("end", ""), spinner_calls)
        self.assertNotIn(("update", "This should not update command-loop spinner"), spinner_calls)
        self.assertNotIn(("succeed", "Command finished; leaving interactive mode..."), spinner_calls)

    def test_dashboard_loop_emits_input_phase_spinner_guard_event(self) -> None:
        state = RunState(run_id="run-7", mode="trees")
        runtime = _RuntimeStub(state)

        def handle_command(_raw: str, current: RunState, _rt: object):  # noqa: ANN001
            return False, current

        with patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
                input_provider=lambda _prompt: "q",
            )

        self.assertEqual(code, 0)
        disabled_events = [
            event
            for event in runtime.events
            if event.get("event") == "ui.spinner.disabled" and event.get("reason") == "input_phase_guard"
        ]
        self.assertTrue(disabled_events)

    def test_dashboard_loop_emits_after_first_render_snapshot_when_enabled(self) -> None:
        state = RunState(run_id="run-snapshot", mode="trees")
        runtime = _RuntimeStub(state)
        runtime.env = {"ENVCTL_DEBUG_PLAN_SNAPSHOT": "1"}

        def handle_command(_raw: str, current: RunState, _rt: object):  # noqa: ANN001
            return False, current

        with patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True):
            code = run_dashboard_command_loop(
                state=state,
                runtime=runtime,
                handle_command=handle_command,
                sanitize=lambda value: value,
                input_provider=lambda _prompt: "q",
            )

        self.assertEqual(code, 0)
        checkpoints = [
            event.get("checkpoint") for event in runtime.events if event.get("event") == "ui.plan_handoff.snapshot"
        ]
        self.assertEqual(checkpoints, ["after_first_dashboard_render"])


if __name__ == "__main__":
    unittest.main()
