# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchTmuxReadinessTests(PlanAgentLaunchSupportTestCase):
    def test_tmux_opencode_ready_wait_allows_slow_cold_start(self) -> None:
        self.assertIsNotNone(_wait_for_tmux_cli_ready)
        clock = {"now": 0.0}
        runtime = _RuntimeHarness(
            config=load_config(
                {
                    "RUN_REPO_ROOT": "/tmp/repo",
                    "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                }
            ),
            env={},
            process_runner=_RecordingRunner(),
        )

        def monotonic() -> float:
            return clock["now"]

        def sleep(seconds: float) -> None:
            clock["now"] += float(seconds)

        def screen(*_args: object, **_kwargs: object) -> str:
            if clock["now"] >= 8.0:
                return '  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo /status\n'
            return "Loading workspace...\n"

        with (
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=monotonic),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", side_effect=sleep),
            patch("envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen", side_effect=screen),
        ):
            ready = _wait_for_tmux_cli_ready(
                runtime,
                session_name="envctl-test",
                window_name="feature-a",
                cli="opencode",
            )

        self.assertTrue(ready.ready)
        self.assertEqual(ready.reason, "ready")
        self.assertGreaterEqual(clock["now"], 8.0)

    def test_tmux_opencode_ready_wait_reports_timeout(self) -> None:
        self.assertIsNotNone(_wait_for_tmux_cli_ready)
        clock = {"now": 0.0}
        runtime = _RuntimeHarness(
            config=load_config(
                {
                    "RUN_REPO_ROOT": "/tmp/repo",
                    "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                }
            ),
            env={},
            process_runner=_RecordingRunner(),
        )

        def monotonic() -> float:
            return clock["now"]

        def sleep(seconds: float) -> None:
            clock["now"] += float(seconds)

        def screen(*_args: object, **_kwargs: object) -> str:
            return "Loading workspace...\n"

        with (
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=monotonic),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", side_effect=sleep),
            patch("envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen", side_effect=screen),
        ):
            ready = _wait_for_tmux_cli_ready(
                runtime,
                session_name="envctl-test",
                window_name="feature-a",
                cli="opencode",
            )

        self.assertFalse(ready.ready)
        self.assertEqual(ready.reason, "opencode_ready_timeout")
        self.assertIn("Loading workspace", ready.screen_excerpt)
