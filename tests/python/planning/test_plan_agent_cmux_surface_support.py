from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.planning.plan_agent.cmux_surface_support import (
    create_surface,
    paste_surface_text,
    prepare_surface,
    run_cmux_command,
    send_surface_key,
    wait_for_cli_ready,
    wait_for_direct_prompt_ready,
    wait_for_prompt_picker_ready,
    wait_for_prompt_submit_ready,
)


class _RecordingRunner:
    def __init__(self, *, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.commands: list[list[str]] = []

    def run(self, command, **_kwargs):  # noqa: ANN001, ANN003
        self.commands.append(list(command))
        return subprocess.CompletedProcess(
            args=command,
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
        )


def _runtime(runner: _RecordingRunner) -> SimpleNamespace:
    repo = Path(tempfile.mkdtemp())
    events: list[tuple[str, dict[str, object]]] = []

    def emit(event: str, **payload: object) -> None:
        events.append((event, payload))

    return SimpleNamespace(
        config=SimpleNamespace(base_dir=repo),
        env={"ENVCTL_TEST": "1"},
        process_runner=runner,
        _emit=emit,
        events=events,
    )


class PlanAgentCmuxSurfaceSupportTests(unittest.TestCase):
    def test_create_surface_returns_surface_id_from_command_output(self) -> None:
        runner = _RecordingRunner(stdout="surface:42\n")
        runtime = _runtime(runner)

        self.assertEqual(create_surface(runtime, workspace_id="workspace:7"), ("surface:42", None))
        self.assertEqual(
            runner.commands,
            [["cmux", "new-surface", "--workspace", "workspace:7"]],
        )

    def test_create_surface_returns_process_error_on_failure(self) -> None:
        runner = _RecordingRunner(returncode=1, stderr="no workspace")
        runtime = _runtime(runner)

        self.assertEqual(create_surface(runtime, workspace_id="workspace:7"), (None, "no workspace"))

    def test_run_cmux_command_emits_failure_with_command_name_and_error(self) -> None:
        runner = _RecordingRunner(returncode=17, stderr="cmux exploded")
        runtime = _runtime(runner)

        self.assertEqual(
            run_cmux_command(runtime, ["cmux", "send-key", "--workspace", "workspace:1", "enter"]),
            "cmux exploded",
        )
        self.assertEqual(
            runtime.events,
            [
                (
                    "planning.agent_launch.failed",
                    {"reason": "cmux_command_failed", "command": "send-key", "error": "cmux exploded"},
                )
            ],
        )

    def test_send_surface_key_maps_enter_for_current_cmux(self) -> None:
        runner = _RecordingRunner()
        runtime = _runtime(runner)

        self.assertIsNone(
            send_surface_key(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:42",
                key="enter",
            )
        )
        self.assertEqual(
            runner.commands,
            [["cmux", "send-key", "--workspace", "workspace:7", "--surface", "surface:42", "Enter"]],
        )

    def test_send_surface_key_maps_escape_for_current_cmux(self) -> None:
        runner = _RecordingRunner()
        runtime = _runtime(runner)

        self.assertIsNone(
            send_surface_key(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:42",
                key="escape",
            )
        )
        self.assertEqual(
            runner.commands,
            [["cmux", "send-key", "--workspace", "workspace:7", "--surface", "surface:42", "Escape"]],
        )

    def test_paste_surface_text_uses_stable_buffer_name_and_paste_command(self) -> None:
        runner = _RecordingRunner()
        runtime = _runtime(runner)

        self.assertIsNone(
            paste_surface_text(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:42",
                text="hello",
            )
        )
        self.assertEqual(
            runner.commands,
            [
                ["cmux", "set-buffer", "--name", "envctl-surface-42", "hello"],
                [
                    "cmux",
                    "paste-buffer",
                    "--name",
                    "envctl-surface-42",
                    "--workspace",
                    "workspace:7",
                    "--surface",
                    "surface:42",
                ],
            ],
        )

    def test_prepare_surface_renames_then_respawns_without_sleeping_in_tests(self) -> None:
        runner = _RecordingRunner()
        runtime = _runtime(runner)

        with patch("envctl_engine.planning.plan_agent.cmux_surface_support.time.sleep") as sleep:
            self.assertIsNone(
                prepare_surface(
                    runtime,
                    workspace_id="workspace:8",
                    surface_id="surface:5",
                    tab_title="feature-a",
                    shell_command="exec zsh",
                )
            )

        self.assertEqual(sleep.call_count, 1)
        self.assertEqual(
            runner.commands,
            [
                ["cmux", "rename-tab", "--workspace", "workspace:8", "--surface", "surface:5", "feature-a"],
                [
                    "cmux",
                    "respawn-pane",
                    "--workspace",
                    "workspace:8",
                    "--surface",
                    "surface:5",
                    "--command",
                    "exec zsh",
                ],
            ],
        )

    def test_wait_for_cli_ready_returns_timeout_with_screen_excerpt(self) -> None:
        runner = _RecordingRunner(stdout="still loading\n")
        runtime = _runtime(runner)

        with (
            patch("envctl_engine.planning.plan_agent.cmux_surface_support.time.monotonic", side_effect=[0.0, 0.1, 1.0]),
            patch("envctl_engine.planning.plan_agent.cmux_surface_support.time.sleep"),
        ):
            error = wait_for_cli_ready(
                runtime,
                workspace_id="workspace:8",
                surface_id="surface:5",
                cli="codex",
                cli_ready_delay_seconds=0.5,
            )

        self.assertEqual(error, "codex_ready_timeout: still loading")

    def test_wait_for_prompt_picker_ready_returns_timeout_with_screen_excerpt(self) -> None:
        runner = _RecordingRunner(stdout="prompt not expanded\n")
        runtime = _runtime(runner)

        with (
            patch("envctl_engine.planning.plan_agent.cmux_surface_support.time.monotonic", side_effect=[0.0, 0.1, 999.0]),
            patch("envctl_engine.planning.plan_agent.cmux_surface_support.time.sleep"),
        ):
            error = wait_for_prompt_picker_ready(
                runtime,
                workspace_id="workspace:8",
                surface_id="surface:5",
                cli="codex",
                prompt_text="implement this",
            )

        self.assertEqual(error, "codex_prompt_picker_ready_timeout: prompt not expanded")

    def test_wait_for_direct_prompt_ready_polls_until_pasted_prompt_is_visible(self) -> None:
        runner = _RecordingRunner(stdout="› /goal Implement this task\n")
        runtime = _runtime(runner)

        with (
            patch("envctl_engine.planning.plan_agent.cmux_surface_support.time.monotonic", side_effect=[0.0, 0.1]),
            patch("envctl_engine.planning.plan_agent.cmux_surface_support.time.sleep"),
        ):
            error = wait_for_direct_prompt_ready(
                runtime,
                workspace_id="workspace:8",
                surface_id="surface:5",
                prompt_text="/goal Implement this task",
            )

        self.assertIsNone(error)

    def test_wait_for_direct_prompt_ready_accepts_collapsed_long_paste_marker(self) -> None:
        runner = _RecordingRunner(stdout="› [Pasted Content 6647 chars]\n")
        runtime = _runtime(runner)

        with (
            patch("envctl_engine.planning.plan_agent.cmux_surface_support.time.monotonic", side_effect=[0.0, 0.1]),
            patch("envctl_engine.planning.plan_agent.cmux_surface_support.time.sleep"),
        ):
            error = wait_for_direct_prompt_ready(
                runtime,
                workspace_id="workspace:8",
                surface_id="surface:5",
                prompt_text="You are implementing real code.\n" + ("Validate evidence.\n" * 80),
            )

        self.assertIsNone(error)

    def test_wait_for_direct_prompt_ready_returns_timeout_with_screen_excerpt(self) -> None:
        runner = _RecordingRunner(stdout="prompt still empty\n")
        runtime = _runtime(runner)

        with (
            patch("envctl_engine.planning.plan_agent.cmux_surface_support.time.monotonic", side_effect=[0.0, 0.1, 999.0]),
            patch("envctl_engine.planning.plan_agent.cmux_surface_support.time.sleep"),
        ):
            error = wait_for_direct_prompt_ready(
                runtime,
                workspace_id="workspace:8",
                surface_id="surface:5",
                prompt_text="/goal Implement this task",
            )

        self.assertEqual(error, "direct_prompt_ready_timeout: prompt still empty")

    def test_wait_for_prompt_submit_ready_returns_timeout_with_screen_excerpt(self) -> None:
        runner = _RecordingRunner(stdout="picker still visible\n")
        runtime = _runtime(runner)

        with (
            patch("envctl_engine.planning.plan_agent.cmux_surface_support.time.monotonic", side_effect=[0.0, 0.1, 999.0]),
            patch("envctl_engine.planning.plan_agent.cmux_surface_support.time.sleep"),
        ):
            error = wait_for_prompt_submit_ready(
                runtime,
                workspace_id="workspace:8",
                surface_id="surface:5",
                cli="opencode",
                prompt_text="implement this",
            )

        self.assertEqual(error, "opencode_prompt_submit_ready_timeout: picker still visible")


if __name__ == "__main__":
    unittest.main()
