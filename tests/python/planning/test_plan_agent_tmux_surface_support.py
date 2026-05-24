from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
import unittest

from envctl_engine.planning.plan_agent import tmux_surface_support


class _Runtime:
    def __init__(self) -> None:
        self.config = SimpleNamespace(base_dir=Path("/repo"))
        self.env = {"ENVCTL_TEST": "1"}
        self.events: list[tuple[str, dict[str, object]]] = []

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, payload))


class _ProbeRunner:
    def __init__(self, *results: subprocess.CompletedProcess[str]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, _runtime: object, command: tuple[str, ...], *, cwd: Path) -> subprocess.CompletedProcess[str]:
        self.calls.append(command)
        if self.results:
            return self.results.pop(0)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


class _SubprocessModule:
    DEVNULL = subprocess.DEVNULL

    def __init__(self, *results: subprocess.CompletedProcess[str]) -> None:
        self.results = list(results)
        self.calls: list[dict[str, object]] = []

    def run(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.calls.append({"command": command, **kwargs})
        if self.results:
            return self.results.pop(0)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


class TmuxSurfaceSupportTests(unittest.TestCase):
    def test_tmux_target_accepts_pane_id_and_window_names(self) -> None:
        self.assertEqual(tmux_surface_support.tmux_target("envctl-feature", "%42"), "%42")
        self.assertEqual(tmux_surface_support.tmux_target("envctl-feature", ""), "envctl-feature")
        self.assertEqual(
            tmux_surface_support.tmux_target("envctl-feature", "implementation"),
            "envctl-feature:implementation",
        )

    def test_send_tmux_key_maps_enter_and_emits_command_failure(self) -> None:
        runtime = _Runtime()
        runner = _ProbeRunner(subprocess.CompletedProcess(["tmux"], 1, stdout="", stderr="missing pane"))

        error = tmux_surface_support.send_tmux_key(
            runtime,
            session_name="envctl-feature",
            window_name="implementation",
            key="enter",
            run_tmux_probe_fn=runner,
            completed_process_error_text_fn=lambda result: str(result.stderr),
        )

        self.assertEqual(error, "missing pane")
        self.assertEqual(
            runner.calls,
            [("tmux", "send-keys", "-t", "envctl-feature:implementation", "Enter")],
        )
        self.assertEqual(runtime.events[0][0], "planning.agent_launch.failed")
        self.assertEqual(runtime.events[0][1]["reason"], "tmux_command_failed")

    def test_read_tmux_screen_falls_back_to_non_alternate_capture(self) -> None:
        runtime = _Runtime()
        runner = _ProbeRunner(
            subprocess.CompletedProcess(["tmux"], 1, stdout="", stderr="no alt"),
            subprocess.CompletedProcess(["tmux"], 0, stdout="ready\n", stderr=""),
        )

        screen = tmux_surface_support.read_tmux_screen(
            runtime,
            session_name="envctl-feature",
            window_name="implementation",
            run_tmux_probe_fn=runner,
        )

        self.assertEqual(screen, "ready\n")
        self.assertEqual(
            runner.calls,
            [
                ("tmux", "capture-pane", "-p", "-a", "-t", "envctl-feature:implementation"),
                ("tmux", "capture-pane", "-p", "-t", "envctl-feature:implementation"),
            ],
        )

    def test_send_tmux_prompt_reports_load_buffer_failure(self) -> None:
        runtime = _Runtime()
        subprocess_module = _SubprocessModule(
            subprocess.CompletedProcess(["tmux"], 1, stdout="", stderr="load failed"),
        )

        error = tmux_surface_support.send_tmux_prompt(
            runtime,
            session_name="envctl-feature",
            window_name="implementation",
            text="hello",
            subprocess_module=subprocess_module,
        )

        self.assertEqual(error, "tmux_load_buffer_failed: load failed")
        self.assertEqual(
            subprocess_module.calls[0]["command"],
            ["tmux", "load-buffer", "-t", "envctl-feature:implementation", "-"],
        )
        self.assertEqual(runtime.events[0][1]["reason"], "tmux_load_buffer_failed")


if __name__ == "__main__":
    unittest.main()
