from __future__ import annotations

from pathlib import Path
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.state.models import RunState  # noqa: E402
from envctl_engine.ui import dashboard_loop_support as support  # noqa: E402


class _RuntimeWithHandler:
    def __init__(self) -> None:
        self.commands: list[tuple[str, str]] = []
        self.events: list[tuple[str, dict[str, object]]] = []

    def _run_interactive_command(self, raw: str, state: RunState) -> tuple[bool, RunState]:
        self.commands.append((raw, state.run_id))
        return False, state

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, dict(payload)))


class DashboardLoopSupportTests(unittest.TestCase):
    def test_run_legacy_dashboard_loop_prefers_runtime_handler(self) -> None:
        runtime = _RuntimeWithHandler()
        state = RunState(run_id="run-1", mode="main")

        def fake_run_dashboard_command_loop(**kwargs):  # type: ignore[no-untyped-def]
            keep_running, next_state = kwargs["handle_command"]("q", state, runtime)
            self.assertFalse(keep_running)
            self.assertEqual(next_state.run_id, "run-1")
            self.assertIs(kwargs["sanitize"], None)
            return 9

        with patch.object(support, "run_dashboard_command_loop", side_effect=fake_run_dashboard_command_loop):
            code = support.run_legacy_dashboard_loop(state=state, runtime=runtime)

        self.assertEqual(code, 9)
        self.assertEqual(runtime.commands, [("q", "run-1")])

    def test_run_legacy_dashboard_loop_uses_fallback_when_runtime_handler_missing(self) -> None:
        runtime = object()
        state = RunState(run_id="run-2", mode="trees")
        calls: list[tuple[str, str]] = []

        def fallback(raw: str, current_state: RunState, runtime_obj: object) -> tuple[bool, RunState]:
            calls.append((raw, current_state.run_id))
            self.assertIs(runtime_obj, runtime)
            return True, current_state

        def fake_run_dashboard_command_loop(**kwargs):  # type: ignore[no-untyped-def]
            keep_running, next_state = kwargs["handle_command"]("help", state, runtime)
            self.assertTrue(keep_running)
            self.assertEqual(next_state.mode, "trees")
            return 3

        with patch.object(support, "run_dashboard_command_loop", side_effect=fake_run_dashboard_command_loop):
            code = support.run_legacy_dashboard_loop(
                state=state,
                runtime=runtime,
                fallback_handler=fallback,
            )

        self.assertEqual(code, 3)
        self.assertEqual(calls, [("help", "run-2")])

    def test_run_legacy_dashboard_loop_preserves_output_tty_state_on_apple_terminal(self) -> None:
        runtime = _RuntimeWithHandler()
        state = RunState(run_id="run-3", mode="trees")

        def fake_run_dashboard_command_loop(**kwargs):  # type: ignore[no-untyped-def]
            return 0

        with (
            patch.dict("os.environ", {"TERM_PROGRAM": "Apple_Terminal"}, clear=False),
            patch.object(support, "normalize_standard_tty_state") as normalize_tty,
            patch.object(support, "run_dashboard_command_loop", side_effect=fake_run_dashboard_command_loop),
        ):
            code = support.run_legacy_dashboard_loop(state=state, runtime=runtime)

        self.assertEqual(code, 0)
        normalize_tty.assert_not_called()

    def test_run_legacy_dashboard_loop_skips_tty_normalization_when_termios_group_disabled(self) -> None:
        runtime = _RuntimeWithHandler()
        state = RunState(run_id="run-4", mode="trees")

        def fake_run_dashboard_command_loop(**kwargs):  # type: ignore[no-untyped-def]
            return 0

        with (
            patch.dict(
                "os.environ",
                {
                    "ENVCTL_DEBUG_PLAN_ORCH_GROUP": "tty",
                    "ENVCTL_DEBUG_PLAN_TTY_GROUP": "reader",
                },
                clear=False,
            ),
            patch.object(support, "normalize_standard_tty_state") as normalize_tty,
            patch.object(support, "run_dashboard_command_loop", side_effect=fake_run_dashboard_command_loop),
        ):
            code = support.run_legacy_dashboard_loop(state=state, runtime=runtime)

        self.assertEqual(code, 0)
        normalize_tty.assert_not_called()
        tty_events = [payload for name, payload in runtime.events if name == "startup.debug_tty_group"]
        self.assertTrue(
            any(
                str(payload.get("group", "")) == "termios"
                and str(payload.get("action", "")) == "normalize_standard_tty_state"
                and payload.get("enabled") is False
                for payload in tty_events
            )
        )


if __name__ == "__main__":
    unittest.main()
