from __future__ import annotations

from pathlib import Path
import subprocess
from types import SimpleNamespace
import unittest

from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree, PlanAgentLaunchConfig
from envctl_engine.planning.plan_agent import tmux_window_support


def _launch_config(*, shell: str) -> PlanAgentLaunchConfig:
    return PlanAgentLaunchConfig(
        enabled=True,
        transport="tmux",
        cli="codex",
        cli_command="codex",
        preset="default",
        codex_cycles=1,
        codex_cycles_warning=None,
        shell=shell,
        require_cmux_context=False,
        cmux_workspace="",
        direct_prompt_enabled=False,
        ulw_loop_prefix=True,
        ulw_suffix=True,
    )


class _ProbeRunner:
    def __init__(self, *results: subprocess.CompletedProcess[str]) -> None:
        self.results = list(results)
        self.calls: list[tuple[tuple[str, ...], Path]] = []

    def __call__(self, _runtime: object, command: tuple[str, ...], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        self.calls.append((command, cwd))
        if self.results:
            return self.results.pop(0)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


class PlanAgentTmuxWindowSupportTests(unittest.TestCase):
    def test_tmux_window_exists_matches_exact_window_name(self) -> None:
        runtime = SimpleNamespace(config=SimpleNamespace(base_dir=Path("/repo")))
        runner = _ProbeRunner(
            subprocess.CompletedProcess(["tmux"], 0, stdout="feature-a\nfeature-a-extra\n", stderr=""),
        )

        self.assertTrue(
            tmux_window_support.tmux_window_exists(
                runtime,
                session_name="envctl-feature",
                window_name="feature-a",
                run_tmux_probe_fn=runner,
            )
        )
        self.assertFalse(
            tmux_window_support.tmux_window_exists(
                runtime,
                session_name="envctl-feature",
                window_name="feature",
                run_tmux_probe_fn=runner,
            )
        )
        self.assertEqual(
            runner.calls[0][0],
            ("tmux", "list-windows", "-t", "envctl-feature", "-F", "#{window_name}"),
        )

    def test_wait_for_tmux_window_ready_polls_until_window_exists(self) -> None:
        calls: list[str] = []
        monotonic_values = iter([0.0, 0.1, 0.2])

        result = tmux_window_support.wait_for_tmux_window_ready(
            runtime=object(),
            session_name="envctl-feature",
            window_name="feature-a",
            tmux_window_exists_fn=lambda *_args, **_kwargs: len(calls) > 0,
            monotonic_fn=lambda: next(monotonic_values),
            sleep_fn=lambda _seconds: calls.append("slept"),
            timeout_seconds=1.0,
            poll_interval_seconds=0.1,
        )

        self.assertIsNone(result)
        self.assertEqual(calls, ["slept"])

    def test_wait_for_tmux_window_ready_reports_timeout(self) -> None:
        monotonic_values = iter([0.0, 0.1, 0.2, 0.3])
        sleeps: list[float] = []

        result = tmux_window_support.wait_for_tmux_window_ready(
            runtime=object(),
            session_name="envctl-feature",
            window_name="feature-a",
            tmux_window_exists_fn=lambda *_args, **_kwargs: False,
            monotonic_fn=lambda: next(monotonic_values),
            sleep_fn=sleeps.append,
            timeout_seconds=0.25,
            poll_interval_seconds=0.1,
        )

        self.assertEqual(result, "tmux_window_unavailable: can't find window: feature-a")
        self.assertEqual(sleeps, [0.1, 0.1])

    def test_enable_tmux_mouse_scrollback_returns_process_error(self) -> None:
        runtime = SimpleNamespace(config=SimpleNamespace(base_dir=Path("/repo")))
        runner = _ProbeRunner(subprocess.CompletedProcess(["tmux"], 1, stdout="", stderr="no session"))

        result = tmux_window_support.enable_tmux_mouse_scrollback(
            runtime,
            session_name="envctl-feature",
            run_tmux_probe_fn=runner,
            completed_process_error_text_fn=lambda completed: str(completed.stderr),
        )

        self.assertEqual(result, "no session")
        self.assertEqual(
            runner.calls,
            [
                (
                    ("tmux", "set-option", "-t", "envctl-feature", "mouse", "on"),
                    Path("/repo"),
                )
            ],
        )

    def test_ensure_tmux_window_creates_session_and_waits_for_window(self) -> None:
        runtime = SimpleNamespace(config=SimpleNamespace(base_dir=Path("/repo")))
        runner = _ProbeRunner(subprocess.CompletedProcess(["tmux"], 0, stdout="", stderr=""))
        launch_config = _launch_config(shell="/bin/zsh")
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="feature-a.md")
        events: list[str] = []

        result = tmux_window_support.ensure_tmux_window(
            runtime,
            session_name="envctl-feature",
            window_name="feature-a-1",
            launch_config=launch_config,
            worktree=worktree,
            tmux_session_exists_fn=lambda *_args, **_kwargs: False,
            run_tmux_probe_fn=runner,
            completed_process_error_text_fn=lambda completed: str(completed.stderr),
            enable_mouse_scrollback_fn=lambda *_args, **_kwargs: events.append("mouse") or None,
            wait_for_window_ready_fn=lambda *_args, **_kwargs: events.append("ready") or None,
        )

        self.assertIsNone(result)
        self.assertEqual(
            runner.calls,
            [
                (
                    (
                        "tmux",
                        "new-session",
                        "-d",
                        "-s",
                        "envctl-feature",
                        "-n",
                        "feature-a-1",
                        "-c",
                        "/repo/trees/feature-a/1",
                        "/bin/zsh",
                    ),
                    Path("/repo"),
                )
            ],
        )
        self.assertEqual(events, ["mouse", "ready"])

    def test_ensure_tmux_window_creates_new_window_in_existing_session(self) -> None:
        runtime = SimpleNamespace(config=SimpleNamespace(base_dir=Path("/repo")))
        runner = _ProbeRunner(subprocess.CompletedProcess(["tmux"], 0, stdout="", stderr=""))
        launch_config = _launch_config(shell="zsh")
        worktree = CreatedPlanWorktree(name="feature-a-1", root=Path("/repo/trees/feature-a/1"), plan_file="feature-a.md")

        result = tmux_window_support.ensure_tmux_window(
            runtime,
            session_name="envctl-feature",
            window_name="feature-a-1",
            launch_config=launch_config,
            worktree=worktree,
            tmux_session_exists_fn=lambda *_args, **_kwargs: True,
            run_tmux_probe_fn=runner,
            completed_process_error_text_fn=lambda completed: str(completed.stderr),
            enable_mouse_scrollback_fn=lambda *_args, **_kwargs: None,
            wait_for_window_ready_fn=lambda *_args, **_kwargs: None,
        )

        self.assertIsNone(result)
        self.assertEqual(runner.calls[0][0][1], "new-window")
        self.assertIn("-c", runner.calls[0][0])


if __name__ == "__main__":
    unittest.main()
