from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from envctl_engine.config import load_config
from envctl_engine.planning import plan_agent_launch_support as launch_support
from envctl_engine.planning.plan_agent_launch_support import CreatedPlanWorktree, launch_plan_agent_terminals
from envctl_engine.runtime.command_router import parse_route

_screen_looks_ready = getattr(launch_support, "_screen_looks_ready")
_prompt_submit_screen_looks_ready = getattr(launch_support, "_prompt_submit_screen_looks_ready")
_tab_title_for_worktree = getattr(launch_support, "_tab_title_for_worktree")
_build_plan_agent_workflow = cast(Any, getattr(launch_support, "_build_plan_agent_workflow", None))
_finalization_instruction_text = cast(Any, getattr(launch_support, "_finalization_instruction_text", None))
_first_cycle_completion_instruction_text = cast(Any, getattr(launch_support, "_first_cycle_completion_instruction_text", None))
_intermediate_cycle_completion_instruction_text = cast(Any, getattr(launch_support, "_intermediate_cycle_completion_instruction_text", None))
_wait_for_codex_queue_ready = cast(Any, getattr(launch_support, "_wait_for_codex_queue_ready", None))
_workflow_step_prompt_text = cast(Any, getattr(launch_support, "_workflow_step_prompt_text", None))
_WorkspaceLaunchTarget = cast(Any, getattr(launch_support, "_WorkspaceLaunchTarget", None))
_ensure_tmux_window = cast(Any, getattr(launch_support, "_ensure_tmux_window", None))
_tmux_session_name_for_worktree = cast(Any, getattr(launch_support, "_tmux_session_name_for_worktree", None))
_run_tmux_worktree_bootstrap = cast(Any, getattr(launch_support, "_run_tmux_worktree_bootstrap", None))


def _launch_config_for_tests(
    *,
    cli: str = "codex",
    direct_prompt_enabled: bool = False,
    ulw_loop_prefix: bool = False,
    ulw_suffix: bool = False,
    preset: str = "implement_task",
) -> launch_support.PlanAgentLaunchConfig:
    return launch_support.PlanAgentLaunchConfig(
        enabled=True,
        transport="cmux",
        cli=cli,
        cli_command=cli,
        preset=preset,
        codex_cycles=0,
        codex_cycles_warning=None,
        shell="zsh",
        require_cmux_context=True,
        cmux_workspace="",
        direct_prompt_enabled=direct_prompt_enabled,
        ulw_loop_prefix=ulw_loop_prefix,
        ulw_suffix=ulw_suffix,
    )


class _RecordingRunner:
    def __init__(self, outputs: list[subprocess.CompletedProcess[str]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.outputs = list(outputs or [])

    def run(self, cmd, *, cwd=None, env=None, timeout=None, stdin=None):  # noqa: ANN001
        _ = cwd, env, timeout, stdin
        self.calls.append([str(part) for part in cmd])
        if self.outputs:
            return self.outputs.pop(0)
        return subprocess.CompletedProcess(args=list(cmd), returncode=0, stdout="", stderr="")


def _monotonic_counter(*, start: float = 0.0, step: float = 0.05):
    value = start - step

    def _next() -> float:
        nonlocal value
        value += step
        return value

    return _next


class _RuntimeHarness:
    def __init__(self, *, config: object, env: dict[str, str], process_runner: _RecordingRunner) -> None:
        self.config = config
        self.env = env
        self.process_runner = process_runner
        self._plan_agent_events: list[dict[str, object]] = []
        self._persist_events_snapshot_calls = 0

    def _command_exists(self, command: str) -> bool:
        return command in {"cmux", "codex", "omx", "opencode", "script", "tmux", "zsh"}

    def _emit(self, event: str, **payload: object) -> None:
        self._plan_agent_events.append({"event": event, **payload})

    def _persist_events_snapshot(self) -> None:
        self._persist_events_snapshot_calls += 1


class _ImmediateThread:
    created: list["_ImmediateThread"] = []

    def __init__(self, *, target=None, kwargs=None, name=None, daemon=None, args=()):  # noqa: ANN001
        self.target = target
        self.kwargs = dict(kwargs or {})
        self.name = name
        self.daemon = daemon
        self.args = tuple(args or ())
        self.started = False
        self.__class__.created.append(self)

    def start(self) -> None:
        self.started = True
        if self.target is not None:
            self.target(*self.args, **self.kwargs)


class PlanAgentLaunchSupportTests(unittest.TestCase):
    def _events(self, runtime: _RuntimeHarness, event_name: str) -> list[dict[str, object]]:
        return [event for event in runtime._plan_agent_events if event.get("event") == event_name]

    def _runtime(self, repo: Path, runtime: Path, *, env: dict[str, str] | None = None) -> _RuntimeHarness:
        resolved_env = {
            "RUN_REPO_ROOT": str(repo),
            "RUN_SH_RUNTIME_DIR": str(runtime),
            **(env or {}),
        }
        config = load_config(resolved_env)
        events: list[dict[str, object]] = []
        runner = _RecordingRunner()
        harness = _RuntimeHarness(config=config, env=resolved_env, process_runner=runner)
        harness._plan_agent_events = events
        return harness

    def test_disabled_feature_returns_skipped_without_running_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
            )

            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.reason, "disabled")
            self.assertEqual(rt.process_runner.calls, [])

    def test_enabled_feature_without_created_worktrees_returns_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(),
            )

            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.reason, "no_new_worktrees")
            self.assertEqual(rt.process_runner.calls, [])

    def test_missing_cmux_context_skips_when_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "skipped")
            self.assertEqual(result.reason, "missing_cmux_context")
            self.assertIn("Plan agent launch skipped", buffer.getvalue())
            self.assertEqual(rt.process_runner.calls, [])

    def test_missing_cmux_executable_returns_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CMUX_WORKSPACE_ID": "workspace:7",
                },
            )
            rt._command_exists = lambda command: command in {"codex", "zsh"}  # type: ignore[assignment]

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "missing_executables")
            self.assertEqual(rt.process_runner.calls, [])

    def test_missing_selected_ai_cli_returns_failed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                    "CMUX_WORKSPACE_ID": "workspace:7",
                },
            )
            rt._command_exists = lambda command: command in {"cmux", "zsh"}  # type: ignore[assignment]

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "missing_executables")
            self.assertEqual(rt.process_runner.calls, [])

    def test_launch_sequence_uses_cmux_commands_for_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:7",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:9\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "• Booting MCP server: playwright (0s • esc to interrupt)\n"
                            "› Explain this codebase\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "› Explain this codebase\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "  /prompts:implement_task\n"
                            "  /prompts:implement_task.bak-20260313-192914\n"
                            "  /prompts:implement_task\n"
                            "  Sisyphus (Ultraworker)\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="  /prompts:implement_task\n  Sisyphus (Ultraworker)\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None) as sleep_mock,
                patch("envctl_engine.planning.plan_agent_launch_support.time.monotonic", new=_monotonic_counter()),
                patch("envctl_engine.planning.plan_agent_launch_support.threading.Thread", _ImmediateThread),
            ):
                _ImmediateThread.created = []
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "new-surface", "--workspace", "workspace:7"])
            self.assertIn(["cmux", "rename-tab", "--workspace", "workspace:7", "--surface", "surface:9", "feature-a-1"], rt.process_runner.calls)
            self.assertIn(["cmux", "respawn-pane", "--workspace", "workspace:7", "--surface", "surface:9", "--command", "zsh"], rt.process_runner.calls)
            self.assertIn(["cmux", "send", "--workspace", "workspace:7", "--surface", "surface:9", f"cd {repo}"], rt.process_runner.calls)
            self.assertIn(
                [
                    "cmux",
                    "send",
                    "--workspace",
                    "workspace:7",
                    "--surface",
                    "surface:9",
                    "codex --dangerously-bypass-approvals-and-sandbox",
                ],
                rt.process_runner.calls,
            )
            self.assertTrue(
                any(
                    call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-9"]
                    and str(call[-1]).startswith("You are implementing real code, end-to-end.")
                    for call in rt.process_runner.calls
                )
            )
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-9", "--workspace", "workspace:7", "--surface", "surface:9"],
                rt.process_runner.calls,
            )
            self.assertEqual(len(_ImmediateThread.created), 1)
            self.assertTrue(_ImmediateThread.created[0].started)
            self.assertEqual(_ImmediateThread.created[0].daemon, False)
            self.assertGreaterEqual(rt.process_runner.calls.count(["cmux", "read-screen", "--workspace", "workspace:7", "--surface", "surface:9", "--lines", "80"]), 2)
            self.assertGreaterEqual(len(sleep_mock.call_args_list), 1)
            self.assertEqual(sleep_mock.call_args_list[0].args[0], 0.15)

    def test_plan_agent_launch_prereqs_switch_to_tmux_for_tmux_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )

            prereqs = launch_support.plan_agent_launch_prereq_commands(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
            )

        self.assertEqual(prereqs, ("tmux", "opencode"))

    def test_resolve_plan_agent_launch_config_uses_tmux_and_opencode_route_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
            )

        self.assertEqual(launch_config.transport, "tmux")
        self.assertEqual(launch_config.cli, "opencode")
        self.assertTrue(launch_config.enabled)

    def test_plan_agent_launch_prereqs_switch_to_omx_for_omx_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )

            prereqs = launch_support.plan_agent_launch_prereq_commands(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
            )

        self.assertEqual(prereqs, ("omx", "tmux", "script", "codex"))

    def test_resolve_plan_agent_launch_config_accepts_omx_route_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
            )

        self.assertEqual(launch_config.transport, "omx")
        self.assertEqual(launch_config.cli, "codex")
        self.assertTrue(launch_config.enabled)

    def test_resolve_plan_agent_launch_config_accepts_explicit_codex_route_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--tmux", "--codex"], env={}),
            )

        self.assertEqual(launch_config.transport, "tmux")
        self.assertEqual(launch_config.cli, "codex")
        self.assertEqual(launch_config.cli_command, "codex --dangerously-bypass-approvals-and-sandbox")
        self.assertTrue(launch_config.enabled)

    def test_launch_sequence_uses_tmux_commands_for_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=1, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="feature-a-1\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout="ask anything\n/status\n> ",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="envctl-test-session\n", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="feature-a-1\n", stderr=""),
                ]
            )

            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="envctl-test-session",
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach-session", "-t", "envctl-test-session"),
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_tmux_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._submit_tmux_prompt_workflow_step", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._resolve_tmux_attach_target", return_value=attach_target),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertIsNotNone(result.attach_target)
            assert result.attach_target is not None
            expected_attach_session = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),
                cli="opencode",
            )
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach-session", "-t", expected_attach_session))
            expected_session_name = next(call[3] for call in rt.process_runner.calls if call[:3] == ["tmux", "has-session", "-t"])
            self.assertIn(["tmux", "has-session", "-t", expected_session_name], rt.process_runner.calls)
            self.assertEqual(expected_session_name, expected_attach_session)
            launch_calls = [call for call in rt.process_runner.calls if call[:2] in (["tmux", "new-session"], ["tmux", "new-window"])]
            self.assertTrue(launch_calls)
            self.assertTrue(any(call[0:5] == ["tmux", "new-session", "-d", "-s", expected_session_name] or call[0:5] == ["tmux", "new-window", "-d", "-t", expected_session_name] for call in launch_calls))
            self.assertIn(["tmux", "send-keys", "-t", f"{expected_session_name}:feature-a-1", "-l", f"cd {shlex.quote(str(repo))}"], rt.process_runner.calls)
            self.assertIn(["tmux", "send-keys", "-t", f"{expected_session_name}:feature-a-1", "Enter"], rt.process_runner.calls)
            self.assertIn(["tmux", "send-keys", "-t", f"{expected_session_name}:feature-a-1", "-l", "opencode"], rt.process_runner.calls)

    def test_tmux_codex_cycles_queue_remaining_workflow_steps(self) -> None:
        self.assertIsNotNone(_run_tmux_worktree_bootstrap)
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="tmux",
                cli="codex",
                cli_command="codex --dangerously-bypass-approvals-and-sandbox",
                preset="implement_task",
                codex_cycles=2,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
            )
            workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=2)

            def resolve_step(*_args, step, **_kwargs):
                return (f"resolved::{step.kind}::{step.text}", None)

            with (
                patch("envctl_engine.planning.plan_agent_launch_support._launch_tmux_cli_bootstrap_commands", return_value=[None]),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_tmux_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._workflow_step_prompt_text", side_effect=resolve_step),
                patch("envctl_engine.planning.plan_agent_launch_support._submit_tmux_prompt_workflow_step", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._send_tmux_prompt", return_value=None) as send_prompt_mock,
                patch("envctl_engine.planning.plan_agent_launch_support._send_tmux_text", return_value=None) as send_text_mock,
                patch("envctl_engine.planning.plan_agent_launch_support._queue_tmux_codex_message", return_value=True) as queue_mock,
            ):
                error = _run_tmux_worktree_bootstrap(
                    rt,
                    session_name="envctl-test-session",
                    window_name="feature-a-1",
                    launch_config=launch_config,
                    workflow=workflow,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            self.assertEqual(send_text_mock.call_count, 1)
            self.assertEqual(send_prompt_mock.call_count, 3)
            self.assertEqual(queue_mock.call_count, 4)
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_queued"),
                [
                    {
                        "event": "planning.agent_launch.workflow_queued",
                        "session_name": "envctl-test-session",
                        "window_name": "feature-a-1",
                        "worktree": "feature-a-1",
                        "cli": "codex",
                        "workflow_mode": "codex_cycles",
                        "codex_cycles": 2,
                        "queued_steps": 4,
                        "transport": "tmux",
                    }
                ],
            )

    def test_omx_transport_rejects_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                },
            )

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a", "--omx", "--opencode"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "unsupported_omx_cli")

    def test_omx_launch_spawns_omx_session_and_bootstraps_existing_tmux_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                },
            )
            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo.resolve(),
                session_name="omx-feature-session",
                window_name="",
                attach_via="attach-session",
                attach_command=("tmux", "attach-session", "-t", "omx-feature-session"),
            )
            popen_calls: list[dict[str, object]] = []

            class _DummyPopen:
                def __init__(self, cmd, **kwargs):  # noqa: ANN001
                    popen_calls.append({"cmd": list(cmd), **kwargs})
                def poll(self):
                    return 0
                def wait(self, timeout=None):  # noqa: ANN001
                    return 0

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.subprocess.Popen", _DummyPopen),
                patch("envctl_engine.planning.plan_agent_launch_support._find_existing_omx_attach_target", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_omx_attach_target", return_value=attach_target),
                patch("envctl_engine.planning.plan_agent_launch_support._run_tmux_existing_session_workflow", return_value=None) as bootstrap_mock,
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(len(popen_calls), 1)
            self.assertEqual(popen_calls[0]["cmd"], ["script", "-qfc", "omx --tmux --madmax", "/dev/null"])
            self.assertEqual(popen_calls[0]["cwd"], str(repo.resolve()))
            env_map = popen_calls[0]["env"]
            assert isinstance(env_map, dict)
            self.assertNotIn("TMUX", env_map)
            self.assertNotIn("TMUX_PANE", env_map)
            self.assertIsInstance(popen_calls[0]["stdin"], int)
            self.assertIsInstance(popen_calls[0]["stdout"], int)
            self.assertIsInstance(popen_calls[0]["stderr"], int)
            self.assertTrue(popen_calls[0]["start_new_session"])
            bootstrap_mock.assert_called_once()
            self.assertIsNotNone(result.attach_target)
            assert result.attach_target is not None
            self.assertEqual(result.attach_target.session_name, "omx-feature-session")
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach-session", "-t", "omx-feature-session"))

    def test_omx_launch_ignores_custom_cli_passthrough_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CLI_CMD": "codex --model gpt-5.4 --dangerously-bypass-approvals-and-sandbox",
                },
            )
            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo.resolve(),
                session_name="omx-feature-session",
                window_name="",
                attach_via="attach-session",
                attach_command=("tmux", "attach-session", "-t", "omx-feature-session"),
            )
            popen_calls: list[dict[str, object]] = []

            class _DummyPopen:
                def __init__(self, cmd, **kwargs):  # noqa: ANN001
                    popen_calls.append({"cmd": list(cmd), **kwargs})
                def poll(self):
                    return 0
                def wait(self, timeout=None):  # noqa: ANN001
                    return 0

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.subprocess.Popen", _DummyPopen),
                patch("envctl_engine.planning.plan_agent_launch_support._find_existing_omx_attach_target", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_omx_attach_target", return_value=attach_target),
                patch("envctl_engine.planning.plan_agent_launch_support._run_tmux_existing_session_workflow", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(len(popen_calls), 1)
            self.assertEqual(popen_calls[0]["cmd"], ["script", "-qfc", "omx --tmux --madmax", "/dev/null"])

    def test_omx_launch_reuses_existing_session_from_session_state_without_spawning(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            session_path = worktree_root / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-session-123",
                        "native_session_id": "omx-feature-session",
                    }
                ),
                encoding="utf-8",
            )
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                },
            )

            with patch(
                "envctl_engine.planning.plan_agent_launch_support._spawn_omx_session_for_worktree",
                side_effect=AssertionError("should not spawn a new OMX session"),
            ) as spawn_mock:
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--codex", "--headless"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "failed")
            self.assertIn("An OMX-managed tmux session already exists for this plan.", result.reason)
            spawn_mock.assert_not_called()
            self.assertIsNotNone(result.attach_target)
            assert result.attach_target is not None
            self.assertEqual(result.attach_target.session_name, "omx-feature-session")
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach-session", "-t", "omx-feature-session"))
            self.assertEqual(
                result.attach_target.new_session_command,
                (
                    "ENVCTL_USE_REPO_WRAPPER=1",
                    str(repo / "bin" / "envctl"),
                    "--plan",
                    "feature-a",
                    "--omx",
                    "--codex",
                    "--tmux-new-session",
                    "--headless",
                ),
            )

    def test_omx_launch_reports_session_unavailable_when_session_state_never_appears(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                },
            )

            class _DummyPopen:
                def __init__(self, cmd, **kwargs):  # noqa: ANN001
                    _ = cmd, kwargs

            buffer = StringIO()
            with (
                redirect_stdout(buffer),
                patch("envctl_engine.planning.plan_agent_launch_support.subprocess.Popen", _DummyPopen),
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support.time.monotonic", new=_monotonic_counter(step=6.1)),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "launch_failed")
            self.assertEqual(len(result.outcomes), 1)
            self.assertEqual(result.outcomes[0].reason, "omx_session_unavailable")
            self.assertEqual(
                self._events(rt, "planning.agent_launch.failed"),
                [
                    {
                        "event": "planning.agent_launch.failed",
                        "reason": "omx_session_unavailable",
                        "worktree": "feature-a-1",
                        "transport": "omx",
                    }
                ],
            )
            self.assertIn("Plan agent launch failed for 1 worktree(s).", buffer.getvalue())

    def test_tmux_launch_reuses_existing_session_for_matching_worktree_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="envctl-existing\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"feature-a-1|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                ]
            )

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),),
            )

            self.assertEqual(result.status, "failed")
            self.assertIsNotNone(result.attach_target)
            assert result.attach_target is not None
            expected_session = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),
                cli="opencode",
            )
            self.assertEqual(result.attach_target.session_name, expected_session)
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach-session", "-t", expected_session))
            self.assertEqual(rt.process_runner.calls[0], ["tmux", "has-session", "-t", expected_session])
            self.assertEqual(rt.process_runner.calls[1], ["tmux", "list-windows", "-t", expected_session, "-F", "#{window_name}|||ENVCTL_TMUX_PATH|||#{pane_current_path}"])

    def test_tmux_existing_session_prompt_yes_attaches_without_launching_new_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            rt._can_interactive_tty = lambda: True  # type: ignore[assignment]
            rt._read_interactive_command_line = lambda prompt: "y"  # type: ignore[assignment]
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="envctl-existing\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"feature-a-1|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                ]
            )

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),),
            )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "existing_tmux_session_attach")
            self.assertIsNotNone(result.attach_target)
            assert result.attach_target is not None
            expected_session = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),
                cli="opencode",
            )
            self.assertEqual(result.attach_target.session_name, expected_session)
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach-session", "-t", expected_session))
            self.assertEqual(len(rt.process_runner.calls), 2)

    def test_existing_tmux_session_prompt_explains_no_creates_new_session(self) -> None:
        prompt_target = launch_support.PlanAgentAttachTarget(
            repo_root=Path("/tmp/repo"),
            session_name="envctl-existing",
            window_name="feature-a-1",
            attach_via="attach-session",
            attach_command=("tmux", "attach-session", "-t", "envctl-existing"),
        )
        captured: list[str] = []
        runtime = self._runtime(Path("/tmp/repo"), Path("/tmp/runtime"))

        def fake_read(prompt: str) -> str:
            captured.append(prompt)
            return "n"

        runtime._read_interactive_command_line = fake_read  # type: ignore[assignment]

        action = launch_support._prompt_existing_tmux_session_action(runtime, attach_target=prompt_target)

        self.assertEqual(action, "new")
        self.assertEqual(len(captured), 1)
        self.assertIn("Y=attach / n=create new session", captured[0])

    def test_tmux_new_session_flag_creates_suffixed_session_for_existing_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            base_session = _tmux_session_name_for_worktree(repo, worktree, cli="opencode")
            new_session = f"{base_session}-2"
            existing_attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name=base_session,
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach-session", "-t", base_session),
            )
            launched_sessions: list[str] = []

            def launch_single(_runtime: object, **kwargs: object) -> launch_support.PlanAgentLaunchOutcome:
                launched_sessions.append(str(kwargs["session_name"]))
                return launch_support.PlanAgentLaunchOutcome(
                    worktree_name=worktree.name,
                    worktree_root=worktree.root,
                    surface_id=None,
                    status="launched",
                )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support._find_existing_tmux_attach_target", return_value=existing_attach_target),
                patch("envctl_engine.planning.plan_agent_launch_support._next_available_tmux_session_name", return_value=new_session) as next_session_mock,
                patch("envctl_engine.planning.plan_agent_launch_support._launch_single_tmux_worktree", side_effect=launch_single),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--tmux-new-session", "--headless"], env={}),
                    created_worktrees=(worktree,),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(launched_sessions, [new_session])
            next_session_mock.assert_called_once_with(rt, base_session)
            self.assertIsNotNone(result.attach_target)
            assert result.attach_target is not None
            self.assertEqual(result.attach_target.session_name, new_session)
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach-session", "-t", new_session))

    def test_find_existing_tmux_attach_target_parses_custom_separator_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="envctl-existing\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"feature-a-1|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                ]
            )

            attach_target = launch_support._find_existing_tmux_attach_target(
                rt,
                repo_root=repo,
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),),
                cli="opencode",
            )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            expected_session = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),
                cli="opencode",
            )
            self.assertEqual(attach_target.session_name, expected_session)
            self.assertEqual(attach_target.window_name, "feature-a-1")

    def test_tmux_session_name_is_different_for_different_worktrees(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree_a = repo / "trees" / "feature-a" / "1"
            worktree_b = repo / "trees" / "feature-b" / "1"
            worktree_a.mkdir(parents=True, exist_ok=True)
            worktree_b.mkdir(parents=True, exist_ok=True)

            session_a = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree_a, plan_file="a.md"),
                cli="opencode",
            )
            session_b = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-b-1", root=worktree_b, plan_file="b.md"),
                cli="opencode",
            )

            self.assertNotEqual(session_a, session_b)

    def test_tmux_session_name_is_different_for_same_worktree_but_different_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            worktree.mkdir(parents=True, exist_ok=True)

            session_opencode = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),
                cli="opencode",
            )
            session_codex = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),
                cli="codex",
            )

            self.assertNotEqual(session_opencode, session_codex)

    def test_ensure_tmux_window_waits_until_window_list_contains_created_window(self) -> None:
        self.assertIsNotNone(_ensure_tmux_window)
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=1, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="other\n", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="feature-a-1\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
            ):
                error = _ensure_tmux_window(
                    rt,
                    session_name="envctl-test-session",
                    window_name="feature-a-1",
                    launch_config=launch_support.PlanAgentLaunchConfig(
                        enabled=True,
                        transport="tmux",
                        cli="opencode",
                        cli_command="opencode",
                        preset="implement_task",
                        codex_cycles=0,
                        codex_cycles_warning=None,
                        shell="zsh",
                        require_cmux_context=True,
                        cmux_workspace="",
                        direct_prompt_enabled=True,
                        ulw_loop_prefix=False,
                        ulw_suffix=False,
                    ),
                    worktree=CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),
                )

            self.assertIsNone(error)
            list_windows_calls = [
                call
                for call in rt.process_runner.calls
                if len(call) >= 6
                and call[0:3] == ["tmux", "list-windows", "-t"]
                and call[3] == "envctl-test-session"
                and call[4] == "-F"
            ]
            self.assertGreaterEqual(len(list_windows_calls), 2)

    def test_resolve_plan_agent_launch_config_parses_codex_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertEqual(launch_config.codex_cycles, 2)
        self.assertIsNone(launch_config.codex_cycles_warning)

    def test_resolve_plan_agent_launch_config_applies_cycles_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CYCLES": "3",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertEqual(launch_config.codex_cycles, 3)
        self.assertIsNone(launch_config.codex_cycles_warning)

    def test_resolve_plan_agent_launch_config_prefers_canonical_cycles_over_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "4",
                    "CYCLES": "2",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertEqual(launch_config.codex_cycles, 4)
        self.assertIsNone(launch_config.codex_cycles_warning)

    def test_resolve_plan_agent_launch_config_reports_invalid_cycles_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CYCLES": "many",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertEqual(launch_config.codex_cycles, 0)
        self.assertEqual(launch_config.codex_cycles_warning, "invalid_codex_cycles")

    def test_resolve_plan_agent_launch_config_bounds_large_cycles_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CYCLES": "999",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertEqual(launch_config.codex_cycles, 10)
        self.assertEqual(launch_config.codex_cycles_warning, "bounded_codex_cycles")

    def test_resolve_plan_agent_launch_config_ignores_invalid_codex_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "many",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertEqual(launch_config.codex_cycles, 0)
        self.assertEqual(launch_config.codex_cycles_warning, "invalid_codex_cycles")

    def test_resolve_plan_agent_launch_config_parses_direct_prompt_and_ulw_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_DIRECT_PROMPT": "true",
                    "ENVCTL_PLAN_AGENT_ULW_LOOP_PREFIX": "true",
                    "ENVCTL_PLAN_AGENT_APPEND_ULW": "true",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(config, {})

        self.assertTrue(launch_config.direct_prompt_enabled)
        self.assertTrue(launch_config.ulw_loop_prefix)
        self.assertTrue(launch_config.ulw_suffix)

    def test_build_plan_agent_workflow_uses_single_prompt_by_default(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=0)

        self.assertEqual(workflow.mode, "single_prompt")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [("submit_direct_prompt", "implement_task")],
        )

    def test_build_plan_agent_workflow_uses_direct_submission_for_ship_release(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(cli="codex", preset="ship_release", codex_cycles=0)

        self.assertEqual(workflow.mode, "single_prompt")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [("submit_direct_prompt", "ship_release")],
        )

    def test_build_plan_agent_workflow_for_single_cycle_adds_finalization_message(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        self.assertIsNotNone(_finalization_instruction_text)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=1)

        self.assertEqual(workflow.mode, "codex_cycles")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [
                ("submit_direct_prompt", "implement_task"),
                ("queue_direct_prompt", "finalize_task"),
            ],
        )

    def test_build_plan_agent_workflow_for_multiple_cycles_queues_continue_and_implement_rounds(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        self.assertIsNotNone(_finalization_instruction_text)
        self.assertIsNotNone(_first_cycle_completion_instruction_text)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=2)

        self.assertEqual(workflow.mode, "codex_cycles")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [
                ("submit_direct_prompt", "implement_task"),
                ("queue_message", _first_cycle_completion_instruction_text()),
                ("queue_direct_prompt", "continue_task"),
                ("queue_direct_prompt", "implement_task"),
                ("queue_direct_prompt", "finalize_task"),
            ],
        )

    def test_build_plan_agent_workflow_for_three_cycles_uses_commit_push_middle_round(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        self.assertIsNotNone(_finalization_instruction_text)
        self.assertIsNotNone(_first_cycle_completion_instruction_text)
        self.assertIsNotNone(_intermediate_cycle_completion_instruction_text)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=3)

        self.assertEqual(workflow.mode, "codex_cycles")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [
                ("submit_direct_prompt", "implement_task"),
                ("queue_message", _first_cycle_completion_instruction_text()),
                ("queue_direct_prompt", "continue_task"),
                ("queue_direct_prompt", "implement_task"),
                ("queue_message", _intermediate_cycle_completion_instruction_text()),
                ("queue_direct_prompt", "continue_task"),
                ("queue_direct_prompt", "implement_task"),
                ("queue_direct_prompt", "finalize_task"),
            ],
        )

    def test_build_plan_agent_workflow_keeps_opencode_on_single_prompt_even_when_cycles_set(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(cli="opencode", preset="implement_task", codex_cycles=2)

        self.assertEqual(workflow.mode, "single_prompt")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [("submit_prompt", "/implement_task")],
        )

    def test_build_plan_agent_workflow_uses_direct_submission_for_opencode_when_enabled(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(
            cli="opencode",
            preset="implement_task",
            codex_cycles=2,
            direct_prompt_enabled=True,
        )

        self.assertEqual(workflow.mode, "single_prompt")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [("submit_direct_prompt", "implement_task")],
        )

    def test_workflow_step_prompt_text_loads_direct_codex_prompt_body(self) -> None:
        self.assertIsNotNone(_workflow_step_prompt_text)
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / ".config" / "envctl" / "codex" / "prompts" / "ship_release.md"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("Ship this release carefully.\n", encoding="utf-8")
            runtime = _RuntimeHarness(
                config=load_config(
                    {
                        "RUN_REPO_ROOT": "/tmp/repo",
                        "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                    }
                ),
                env={"HOME": tmpdir},
                process_runner=_RecordingRunner(),
            )
            step = launch_support._PlanAgentWorkflowStep(kind="submit_direct_prompt", text="ship_release")

            prompt_text, error = _workflow_step_prompt_text(
                runtime,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
                step=step,
            )

        self.assertIsNone(error)
        self.assertEqual(prompt_text, "Ship this release carefully.\n")

    def test_workflow_step_prompt_text_preserves_literal_arguments_mentions_in_review_prompt(self) -> None:
        self.assertIsNotNone(_workflow_step_prompt_text)
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / ".config" / "envctl" / "codex" / "prompts" / "review_worktree_imp.md"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(
                "Inputs:\n$ARGUMENTS\nKeep `$ARGUMENTS` literal in prose.\n",
                encoding="utf-8",
            )
            runtime = _RuntimeHarness(
                config=load_config(
                    {
                        "RUN_REPO_ROOT": "/tmp/repo",
                        "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                    }
                ),
                env={"HOME": tmpdir},
                process_runner=_RecordingRunner(),
            )
            step = launch_support._PlanAgentWorkflowStep(kind="submit_direct_prompt", text="review_worktree_imp")

            prompt_text, error = launch_support._resolve_preset_submission_text(
                runtime,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
                preset="review_worktree_imp",
                arguments="Review bundle: /tmp/review.md\nWorktree directory: /tmp/tree",
            )

        self.assertIsNone(error)
        self.assertIn("Review bundle: /tmp/review.md\nWorktree directory: /tmp/tree", prompt_text)
        self.assertIn("Keep `$ARGUMENTS` literal in prose.", prompt_text)
        self.assertEqual(prompt_text.count("$ARGUMENTS"), 1)

    def test_resolve_preset_submission_text_returns_opencode_direct_body_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / ".config" / "opencode" / "commands" / "implement_task.md"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("Implement this directly.\n", encoding="utf-8")
            runtime = _RuntimeHarness(
                config=load_config(
                    {
                        "RUN_REPO_ROOT": "/tmp/repo",
                        "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                    }
                ),
                env={"HOME": tmpdir},
                process_runner=_RecordingRunner(),
            )
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="cmux",
                cli="opencode",
                cli_command="opencode",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=True,
                ulw_loop_prefix=False,
                ulw_suffix=False,
            )

            prompt_text, error = launch_support._resolve_preset_submission_text(
                runtime,
                launch_config=launch_config,
                cli="opencode",
                preset="implement_task",
            )

        self.assertIsNone(error)
        self.assertEqual(prompt_text, "Implement this directly.\n")

    def test_resolve_preset_submission_text_keeps_slash_mode_for_opencode_by_default(self) -> None:
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
        launch_config = launch_support.PlanAgentLaunchConfig(
            enabled=True,
            transport="cmux",
            cli="opencode",
            cli_command="opencode",
            preset="implement_task",
            codex_cycles=0,
            codex_cycles_warning=None,
            shell="zsh",
            require_cmux_context=True,
            cmux_workspace="",
            direct_prompt_enabled=False,
            ulw_loop_prefix=False,
            ulw_suffix=False,
        )

        prompt_text, error = launch_support._resolve_preset_submission_text(
            runtime,
            launch_config=launch_config,
            cli="opencode",
            preset="implement_task",
        )

        self.assertIsNone(error)
        self.assertEqual(prompt_text, "/implement_task")

    def test_resolve_preset_submission_text_prepends_ulw_loop_for_direct_prompts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prompt_path = Path(tmpdir) / ".config" / "opencode" / "commands" / "implement_task.md"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("Implement this directly.\n", encoding="utf-8")
            runtime = _RuntimeHarness(
                config=load_config(
                    {
                        "RUN_REPO_ROOT": "/tmp/repo",
                        "RUN_SH_RUNTIME_DIR": "/tmp/runtime",
                    }
                ),
                env={"HOME": tmpdir},
                process_runner=_RecordingRunner(),
            )
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="cmux",
                cli="opencode",
                cli_command="opencode",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=True,
                ulw_loop_prefix=True,
                ulw_suffix=False,
            )

            prompt_text, error = launch_support._resolve_preset_submission_text(
                runtime,
                launch_config=launch_config,
                cli="opencode",
                preset="implement_task",
            )

        self.assertIsNone(error)
        self.assertTrue(prompt_text.startswith("/ulw_loop "))
        self.assertIn("Implement this directly.", prompt_text)

    def test_resolve_preset_submission_text_appends_ulw_suffix_in_slash_mode(self) -> None:
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
        launch_config = launch_support.PlanAgentLaunchConfig(
            enabled=True,
            transport="cmux",
            cli="opencode",
            cli_command="opencode",
            preset="implement_task",
            codex_cycles=0,
            codex_cycles_warning=None,
            shell="zsh",
            require_cmux_context=True,
            cmux_workspace="",
            direct_prompt_enabled=False,
            ulw_loop_prefix=False,
            ulw_suffix=True,
        )

        prompt_text, error = launch_support._resolve_preset_submission_text(
            runtime,
            launch_config=launch_config,
            cli="opencode",
            preset="implement_task",
        )

        self.assertIsNone(error)
        self.assertEqual(prompt_text, "/implement_task ulw")

    def test_resolve_preset_submission_text_rejects_ulw_loop_prefix_in_slash_mode(self) -> None:
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
        launch_config = launch_support.PlanAgentLaunchConfig(
            enabled=True,
            transport="cmux",
            cli="opencode",
            cli_command="opencode",
            preset="implement_task",
            codex_cycles=0,
            codex_cycles_warning=None,
            shell="zsh",
            require_cmux_context=True,
            cmux_workspace="",
            direct_prompt_enabled=False,
            ulw_loop_prefix=True,
            ulw_suffix=False,
        )

        prompt_text, error = launch_support._resolve_preset_submission_text(
            runtime,
            launch_config=launch_config,
            cli="opencode",
            preset="implement_task",
        )

        self.assertEqual(prompt_text, "")
        self.assertEqual(error, "prompt_resolution_failed: ulw_loop_prefix_requires_direct_prompt")

    def test_shape_prompt_text_rejects_multiple_slash_commands_for_direct_prompts(self) -> None:
        shaped, error = launch_support._shape_prompt_text(
            "/implement_task",
            direct_prompt=True,
            ulw_loop_prefix=True,
            ulw_suffix=False,
        )

        self.assertEqual(shaped, "")
        self.assertEqual(error, "prompt_resolution_failed: multiple_slash_commands_not_allowed")

    def test_shape_prompt_text_rejects_embedded_second_slash_command_for_direct_prompts(self) -> None:
        shaped, error = launch_support._shape_prompt_text(
            "Implement this directly.\n/implement_task",
            direct_prompt=True,
            ulw_loop_prefix=True,
            ulw_suffix=False,
        )

        self.assertEqual(shaped, "")
        self.assertEqual(error, "prompt_resolution_failed: multiple_slash_commands_not_allowed")

    def test_shape_prompt_text_preserves_existing_ulw_loop_prefix_and_allows_suffix(self) -> None:
        shaped, error = launch_support._shape_prompt_text(
            "/ulw_loop Implement this directly.",
            direct_prompt=True,
            ulw_loop_prefix=True,
            ulw_suffix=True,
        )

        self.assertIsNone(error)
        self.assertEqual(shaped, "/ulw_loop Implement this directly. ulw")

    def test_shape_prompt_text_allows_absolute_path_literals_in_direct_prompts(self) -> None:
        shaped, error = launch_support._shape_prompt_text(
            'Review bundle: "/tmp/review.md"\nWorktree directory: "/tmp/tree"',
            direct_prompt=True,
            ulw_loop_prefix=True,
            ulw_suffix=False,
        )

        self.assertIsNone(error)
        self.assertTrue(shaped.startswith("/ulw_loop "))
        self.assertIn('Review bundle: "/tmp/review.md"', shaped)

    def test_build_plan_agent_workflow_bounds_large_cycle_counts(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=999)

        self.assertEqual(workflow.mode, "codex_cycles")
        self.assertEqual(workflow.codex_cycles, 10)
        self.assertEqual(len(workflow.steps), 1 + (1 + 3 * (workflow.codex_cycles - 1)))

    def test_codex_cycle_launch_queues_follow_up_messages_with_tab(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:7",
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:9\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "› Explain this codebase\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="  /prompts:implement_task\n  Sisyphus (Ultraworker)\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "› /prompts:implement_task\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "› /prompts:implement_task\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "› /prompts:continue_task\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "› /prompts:implement_task\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support.time.monotonic", new=_monotonic_counter()),
                patch("envctl_engine.planning.plan_agent_launch_support.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent_launch_support._queue_codex_message", return_value=True),
            ):
                _ImmediateThread.created = []
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertTrue(
                any(
                    call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-9"]
                    and "You are implementing real code, end-to-end." in str(call[-1])
                    for call in rt.process_runner.calls
                )
            )
            self.assertTrue(
                any(
                    call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-9"]
                    and "You are preparing the next implementation iteration" in str(call[-1])
                    for call in rt.process_runner.calls
                )
            )
            self.assertTrue(
                any(
                    call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-9"]
                    and "You are finalizing an implementation" in str(call[-1])
                    for call in rt.process_runner.calls
                )
            )
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_queued"),
                [
                    {
                        "event": "planning.agent_launch.workflow_queued",
                        "workspace_id": "workspace:7",
                        "surface_id": "surface:9",
                        "worktree": "feature-a-1",
                        "cli": "codex",
                        "workflow_mode": "codex_cycles",
                        "codex_cycles": 2,
                        "queued_steps": 4,
                    }
                ],
            )
            self.assertEqual(rt._persist_events_snapshot_calls, 1)

    def test_wait_for_codex_queue_ready_tolerates_delayed_prompt_return(self) -> None:
        self.assertIsNotNone(_wait_for_codex_queue_ready)
        ready_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "› /prompts:implement_task\n"
        )
        screens = iter(["Booting MCP server...\n"] * 12 + [ready_screen])
        runtime = object()

        with (
            patch(
                "envctl_engine.planning.plan_agent_launch_support._read_surface_screen",
                side_effect=lambda *_args, **_kwargs: next(screens, ready_screen),
            ),
            patch("envctl_engine.planning.plan_agent_launch_support.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
        ):
            ready = _wait_for_codex_queue_ready(runtime, workspace_id="workspace:7", surface_id="surface:9")

        self.assertTrue(ready)

    def test_codex_cycle_queue_types_message_before_waiting_for_tab_ready(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=1)
        queued_steps = workflow.steps[1:]
        self.assertEqual(len(queued_steps), 1)
        pasted_texts: list[str] = []
        sent_keys: list[str] = []

        busy_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "• Working (32s • esc to interrupt)\n"
        )
        typed_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "  You are finalizing an implementation that should already be substantially complete in the current worktree.\n"
            "  tab to queue message\n"
        )
        state = {"typed": False}

        def fake_paste_text(*_args, text, **_kwargs):  # noqa: ANN202, ANN001
            pasted_texts.append(text)
            state["typed"] = True
            return None

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            state["typed"] = False
            return None

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

        with (
            patch("envctl_engine.planning.plan_agent_launch_support._paste_surface_text", side_effect=fake_paste_text),
            patch("envctl_engine.planning.plan_agent_launch_support._send_surface_key", side_effect=fake_send_key),
            patch(
                "envctl_engine.planning.plan_agent_launch_support._read_surface_screen",
                side_effect=lambda *_args, **_kwargs: typed_screen if state["typed"] else busy_screen,
            ),
            patch("envctl_engine.planning.plan_agent_launch_support.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
        ):
            reason = launch_support._queue_codex_workflow_steps(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:9",
                worktree=CreatedPlanWorktree(name="feature-a-1", root=Path("/tmp/repo"), plan_file="a.md"),
                workflow=workflow,
                queued_steps=queued_steps,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
            )

        self.assertIsNone(reason)
        self.assertEqual(len(pasted_texts), 1)
        self.assertIn("You are finalizing an implementation", pasted_texts[0])
        self.assertEqual(sent_keys, ["tab"])

    def test_codex_cycle_queue_direct_prompt_tabs_without_picker_resolution(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body"
        state = {"stage": "typed"}

        queue_hint_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "  Direct queued prompt body\n"
            "  tab to queue message\n"
        )
        committed_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "• Queued follow-up messages\n"
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            if key == "tab":
                state["stage"] = "committed"
            return None

        def fake_read_screen(*_args, **_kwargs):  # noqa: ANN202, ANN001
            if state["stage"] == "typed":
                return queue_hint_screen
            return committed_screen

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

        with (
            patch("envctl_engine.planning.plan_agent_launch_support._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent_launch_support._read_surface_screen", side_effect=fake_read_screen),
            patch("envctl_engine.planning.plan_agent_launch_support.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
        ):
            queued = launch_support._queue_codex_message(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:9",
                text=queued_text,
                require_text_match=False,
            )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])

    def test_codex_cycle_queue_direct_prompt_requires_visible_message_text_before_tab(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body"
        queue_hint_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "  tab to queue message\n"
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            return None

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

        with (
            patch("envctl_engine.planning.plan_agent_launch_support._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent_launch_support._read_surface_screen", return_value=queue_hint_screen),
            patch("envctl_engine.planning.plan_agent_launch_support.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
        ):
            queued = launch_support._queue_codex_message(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:9",
                text=queued_text,
                require_text_match=False,
            )

        self.assertFalse(queued)
        self.assertEqual(sent_keys, [])

    def test_codex_cycle_queue_direct_prompt_accepts_pasted_content_placeholder(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body\nwith multiple lines"
        state = {"stage": "typed"}
        queue_hint_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "› [Pasted Content 6674 chars]\n"
            "  tab to queue message\n"
        )
        committed_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "• Queued follow-up messages\n"
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            if key == "tab":
                state["stage"] = "committed"
            return None

        def fake_read_screen(*_args, **_kwargs):  # noqa: ANN202, ANN001
            if state["stage"] == "typed":
                return queue_hint_screen
            return committed_screen

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

        with (
            patch("envctl_engine.planning.plan_agent_launch_support._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent_launch_support._read_surface_screen", side_effect=fake_read_screen),
            patch("envctl_engine.planning.plan_agent_launch_support.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
        ):
            queued = launch_support._queue_codex_message(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:9",
                text=queued_text,
                require_text_match=False,
            )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])

    def test_review_prompt_arguments_preserve_newlines_for_direct_codex_submission(self) -> None:
        rendered = launch_support._review_prompt_arguments(
            project_name="feature-a-1",
            project_root=Path("/tmp/worktree path"),
            review_bundle_path=Path("/tmp/review bundle.md"),
            original_plan_path=Path("/tmp/original plan.md"),
        )

        self.assertEqual(
            rendered,
            'Project: feature-a-1\n'
            'Review bundle: "/tmp/review bundle.md"\n'
            'Worktree directory: "/tmp/worktree path"\n'
            'Original plan file: "/tmp/original plan.md"',
        )

    def test_prompt_submit_screen_accepts_multiline_direct_prompt_once_each_line_is_visible(self) -> None:
        screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "Review bundle: /tmp/review.md\n"
            "Worktree directory: /tmp/tree\n"
            "Original plan file: /tmp/plan.md\n"
        )
        prompt_text = "Review bundle: /tmp/review.md\nWorktree directory: /tmp/tree\nOriginal plan file: /tmp/plan.md"

        self.assertTrue(_prompt_submit_screen_looks_ready("codex", screen, prompt_text))

    def test_prompt_submit_screen_rejects_multiline_direct_prompt_when_line_missing(self) -> None:
        screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "Review bundle: /tmp/review.md\n"
            "Worktree directory: /tmp/tree\n"
        )
        prompt_text = "Review bundle: /tmp/review.md\nWorktree directory: /tmp/tree\nOriginal plan file: /tmp/plan.md"

        self.assertFalse(_prompt_submit_screen_looks_ready("codex", screen, prompt_text))

    def test_codex_cycle_queue_failure_falls_back_to_initial_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:7",
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "1",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:9\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "╭───────────────────────────────────────────────────╮\n"
                            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
                            "│ model:     gpt-5.4 high   fast   /model to change │\n"
                            "│ directory: ~/repo                                 │\n"
                            "› Explain this codebase\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="  /prompts:implement_task\n  Sisyphus (Ultraworker)\n",
                        stderr="",
                    ),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support.time.monotonic", new=_monotonic_counter()),
                patch("envctl_engine.planning.plan_agent_launch_support.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_codex_queue_ready", return_value=True),
                patch(
                    "envctl_engine.planning.plan_agent_launch_support._paste_surface_text",
                    side_effect=[None, "queue failed"],
                ),
            ):
                _ImmediateThread.created = []
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(self._events(rt, "planning.agent_launch.failed"), [])
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_fallback"),
                [
                    {
                        "event": "planning.agent_launch.workflow_fallback",
                        "workspace_id": "workspace:7",
                        "surface_id": "surface:9",
                        "worktree": "feature-a-1",
                        "cli": "codex",
                        "workflow_mode": "codex_cycles",
                        "codex_cycles": 1,
                        "reason": "queue_send_failed",
                    }
                ],
            )
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_queue_failed"),
                [
                    {
                        "event": "planning.agent_launch.workflow_queue_failed",
                        "workspace_id": "workspace:7",
                        "surface_id": "surface:9",
                        "worktree": "feature-a-1",
                        "cli": "codex",
                        "workflow_mode": "codex_cycles",
                        "codex_cycles": 1,
                        "reason": "queue_send_failed",
                    }
                ],
            )

    def test_codex_cycle_launch_uses_cycles_alias_in_summary_and_workflow_selection(self) -> None:
        self.assertIsNotNone(_WorkspaceLaunchTarget)
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:7",
                    "CYCLES": "3",
                },
            )

            def _fake_launch_single_worktree(*args, **kwargs):  # noqa: ANN202, ANN001
                worktree = kwargs["worktree"]
                return launch_support.PlanAgentLaunchOutcome(
                    worktree_name=worktree.name,
                    worktree_root=worktree.root,
                    surface_id="surface:9",
                    status="launched",
                )

            buffer = StringIO()
            with (
                redirect_stdout(buffer),
                patch(
                    "envctl_engine.planning.plan_agent_launch_support._ensure_workspace_id",
                    return_value=_WorkspaceLaunchTarget(workspace_id="workspace:7", created=False),
                ),
                patch(
                    "envctl_engine.planning.plan_agent_launch_support._launch_single_worktree",
                    side_effect=_fake_launch_single_worktree,
                ),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "launched")
        self.assertIn("Plan agent launch queued Codex cycle workflow (cycles=3)", buffer.getvalue())
        self.assertEqual(
            self._events(rt, "planning.agent_launch.workflow_selected"),
            [
                {
                    "event": "planning.agent_launch.workflow_selected",
                    "workspace_id": "workspace:7",
                    "warning": None,
                    "enabled": True,
                    "cli": "codex",
                    "created_worktree_count": 1,
                    "workflow_mode": "codex_cycles",
                    "codex_cycles": 3,
                }
            ],
        )

    def test_tab_title_for_worktree_uses_first_and_last_three_words(self) -> None:
        self.assertEqual(
            _tab_title_for_worktree("refactoring_envctl_ai_pr_fix-1"),
            "refactoring_ai_pr_fix-1",
        )

    def test_tab_title_for_worktree_drops_third_from_last_word_when_still_too_long(self) -> None:
        self.assertEqual(
            _tab_title_for_worktree("refactoring_envctl_python_engine_cutover_reliability_plan-1"),
            "refactoring_reliability_plan-1",
        )

    def test_tab_title_for_worktree_skips_low_signal_origin_token(self) -> None:
        self.assertEqual(
            _tab_title_for_worktree("features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1"),
            "features_review_preset-1",
        )

    def test_launch_sequence_supports_opencode_and_default_implementation_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                    "ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:4  envctl  [selected]\n  workspace:8  envctl implementation\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:12\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="Loading workspace...\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout='  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo  ⊙ 3 MCP /status    1.2.27\n',
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "  ┃ /implement_task                                                   ┃\n"
                            "  ┃ /implement_task.bak-20260313-192914                               ┃\n"
                            "  ┃ /implement_task.bak-20260315-173140                               ┃\n"
                            "  ┃                                                                 \n"
                            "  ┃  /implement_task                                                 \n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            "  ┃                                                                 \n"
                            "  ┃  /implement_task                                                 \n"
                            "  ┃                                                                 \n"
                            "  ┃  Sisyphus (Ultraworker)                                          \n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None) as sleep_mock,
                patch("envctl_engine.planning.plan_agent_launch_support.time.monotonic", new=_monotonic_counter()),
                patch("envctl_engine.planning.plan_agent_launch_support.threading.Thread", _ImmediateThread),
            ):
                _ImmediateThread.created = []
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-surface", "--workspace", "workspace:8"])
            self.assertIn(
                ["cmux", "respawn-pane", "--workspace", "workspace:8", "--surface", "surface:12", "--command", "zsh"],
                rt.process_runner.calls,
            )
            self.assertIn(["cmux", "send", "--workspace", "workspace:8", "--surface", "surface:12", f"cd {repo}"], rt.process_runner.calls)
            self.assertIn(["cmux", "send-key", "--workspace", "workspace:8", "--surface", "surface:12", "enter"], rt.process_runner.calls)
            self.assertIn(["cmux", "send", "--workspace", "workspace:8", "--surface", "surface:12", "opencode"], rt.process_runner.calls)
            self.assertIn(["cmux", "send", "--workspace", "workspace:8", "--surface", "surface:12", "/implement_task"], rt.process_runner.calls)
            self.assertEqual(len(_ImmediateThread.created), 1)
            self.assertTrue(_ImmediateThread.created[0].started)
            self.assertEqual(_ImmediateThread.created[0].daemon, False)
            self.assertIn(["cmux", "send-key", "--workspace", "workspace:8", "--surface", "surface:12", "ctrl+e"], rt.process_runner.calls)
            self.assertGreaterEqual(rt.process_runner.calls.count(["cmux", "read-screen", "--workspace", "workspace:8", "--surface", "surface:12", "--lines", "80"]), 3)
            self.assertGreaterEqual(
                rt.process_runner.calls.count(
                    ["cmux", "send-key", "--workspace", "workspace:8", "--surface", "surface:12", "enter"]
                ),
                2,
            )
            self.assertNotIn(
                ["cmux", "send-key", "--workspace", "workspace:8", "--surface", "surface:12", "tab"],
                rt.process_runner.calls,
            )
            self.assertGreaterEqual(len(sleep_mock.call_args_list), 2)
            self.assertEqual(sleep_mock.call_args_list[0].args[0], 0.15)
            self.assertIn(0.1, [call.args[0] for call in sleep_mock.call_args_list[1:]])

    def test_created_default_workspace_reuses_single_starter_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CMUX_WORKSPACE_ID": "workspace:4",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:4  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:9\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:77\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_prompt_picker_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_prompt_submit_ready", return_value=None),
            ):
                _ImmediateThread.created = []
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-workspace", "--cwd", str(repo.resolve())])
            self.assertEqual(rt.process_runner.calls[2], ["cmux", "current-workspace"])
            self.assertEqual(
                rt.process_runner.calls[3],
                ["cmux", "rename-workspace", "--workspace", "workspace:9", "envctl implementation"],
            )
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "list-pane-surfaces", "--workspace", "workspace:9"])
            self.assertNotIn(["cmux", "new-surface", "--workspace", "workspace:9"], rt.process_runner.calls)
            self.assertIn(
                ["cmux", "rename-tab", "--workspace", "workspace:9", "--surface", "surface:77", "feature-a-1"],
                rt.process_runner.calls,
            )
            self.assertIn(
                ["cmux", "respawn-pane", "--workspace", "workspace:9", "--surface", "surface:77", "--command", "zsh"],
                rt.process_runner.calls,
            )
            self.assertIn(["cmux", "send", "--workspace", "workspace:9", "--surface", "surface:77", f"cd {repo}"], rt.process_runner.calls)
            self.assertIn(
                [
                    "cmux",
                    "send",
                    "--workspace",
                    "workspace:9",
                    "--surface",
                    "surface:77",
                    "codex --dangerously-bypass-approvals-and-sandbox",
                ],
                rt.process_runner.calls,
            )
            self.assertTrue(
                any(
                    call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-77"]
                    and str(call[-1]).startswith("You are implementing real code, end-to-end.")
                    for call in rt.process_runner.calls
                )
            )
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-77", "--workspace", "workspace:9", "--surface", "surface:77"],
                rt.process_runner.calls,
            )
            self.assertEqual(len(_ImmediateThread.created), 1)

    def test_opencode_ready_screen_accepts_loaded_composer_layout(self) -> None:
        screen = '  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo  ⊙ 3 MCP /status    1.2.27\n'
        self.assertTrue(launch_support._screen_looks_ready("opencode", screen))

    def test_codex_ready_screen_requires_boot_to_finish(self) -> None:
        loading = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "• Booting MCP server: playwright (0s • esc to interrupt)\n"
            "› Explain this codebase\n"
        )
        model_loading = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     loading   /model to change             │\n"
            "│ directory: ~/repo                                 │\n"
            "› /prompts:implement_task\n"
        )
        ready = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "› Explain this codebase\n"
        )
        self.assertFalse(_screen_looks_ready("codex", loading))
        self.assertFalse(_screen_looks_ready("codex", model_loading))
        self.assertTrue(_screen_looks_ready("codex", ready))

    def test_ai_cli_ready_window_uses_five_second_fallback(self) -> None:
        self.assertEqual(launch_support._cli_ready_delay_seconds("codex"), 5.0)
        self.assertEqual(launch_support._cli_ready_delay_seconds("opencode"), 5.0)

    def test_workspace_entries_are_parsed_from_list_output(self) -> None:
        payload = """
        * workspace:1  envctl  [selected]
          workspace:2  envctl implementation
          workspace:3  supportopia
        """
        self.assertEqual(
            launch_support._workspace_entries_from_list_output(payload),
            (
                ("workspace:1", "envctl"),
                ("workspace:2", "envctl implementation"),
                ("workspace:3", "supportopia"),
            ),
        )

    def test_surface_ids_are_parsed_from_list_output(self) -> None:
        payload = """
        pane:1
          surface:20 [terminal] "~/repo"
          surface:21 [terminal] "feature-a-1" [selected]
        """
        self.assertEqual(
            launch_support._surface_ids_from_list_output(payload),
            ("surface:20", "surface:21"),
        )

    def test_surface_ids_parser_dedupes_repeated_surface_refs(self) -> None:
        payload = """
        pane:1
          surface:20 [terminal] "~/repo"
        pane:2
          surface:20 [terminal] "~/repo" [selected]
        """
        self.assertEqual(
            launch_support._surface_ids_from_list_output(payload),
            ("surface:20",),
        )

    def test_surface_ids_parser_ignores_non_numeric_surface_tokens(self) -> None:
        payload = """
        pane:1
          surface:notes [terminal] "~/repo"
          surface:21 [terminal] "feature-a-1" [selected]
        """
        self.assertEqual(
            launch_support._surface_ids_from_list_output(payload),
            ("surface:21",),
        )

    def test_workspace_ref_is_parsed_from_identify_output(self) -> None:
        payload = """
        {
          "caller": {
            "workspace_ref": "workspace:4"
          },
          "focused": {
            "workspace_ref": "workspace:8"
          }
        }
        """
        self.assertEqual(launch_support._workspace_ref_from_identify_output(payload), "workspace:4")

    def test_opencode_ready_screen_rejects_loading_text_even_with_prompt_glyphs(self) -> None:
        screen = "Loading workspace...\n  ›\n"
        self.assertFalse(_screen_looks_ready("opencode", screen))

    def test_opencode_prompt_submit_screen_waits_for_single_selected_command(self) -> None:
        pending = (
            "  ┃ /implement_task                                                   ┃\n"
            "  ┃ /implement_task.bak-20260313-192914                               ┃\n"
            "  ┃ /implement_task.bak-20260315-173140                               ┃\n"
            "  ┃                                                                 \n"
            "  ┃  /implement_task                                                 \n"
        )
        ready = (
            "  ┃                                                                 \n"
            "  ┃  /implement_task                                                 \n"
            "  ┃                                                                 \n"
            "  ┃  Sisyphus (Ultraworker)                                          \n"
        )
        broken = "  ┃ No matching items ┃\n  ┃  /implement_task/implement_task\n"
        self.assertFalse(_prompt_submit_screen_looks_ready("opencode", pending, "/implement_task"))
        self.assertFalse(_prompt_submit_screen_looks_ready("opencode", broken, "/implement_task"))
        self.assertTrue(_prompt_submit_screen_looks_ready("opencode", ready, "/implement_task"))

    def test_explicit_workspace_override_implies_enablement_and_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:9",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:33\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "new-surface", "--workspace", "workspace:9"])
            self.assertNotIn(["cmux", "current-workspace"], rt.process_runner.calls)

    def test_explicit_workspace_override_resolves_workspace_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "envctl",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:33\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-surface", "--workspace", "workspace:1"])
            self.assertNotIn(["cmux", "current-workspace"], rt.process_runner.calls)

    def test_cmux_alias_enables_default_implementation_workspace_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "CMUX": "true",
                    "CMUX_WORKSPACE_ID": "workspace:7",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:7  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:9\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:10\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-workspace", "--cwd", str(repo.resolve())])
            self.assertEqual(rt.process_runner.calls[2], ["cmux", "current-workspace"])
            self.assertEqual(rt.process_runner.calls[3], ["cmux", "rename-workspace", "--workspace", "workspace:9", "envctl implementation"])
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "list-pane-surfaces", "--workspace", "workspace:9"])
            self.assertNotIn(["cmux", "new-surface", "--workspace", "workspace:9"], rt.process_runner.calls)

    def test_cmux_alias_resolves_uuid_workspace_context_before_default_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "CMUX": "true",
                    "CMUX_WORKSPACE_ID": "B2F931FE-491C-448F-8B45-0BA5C932C8F0",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:7  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout=(
                            '{\n'
                            '  "caller": {\n'
                            '    "workspace_ref": "workspace:7"\n'
                            "  },\n"
                            '  "focused": {\n'
                            '    "workspace_ref": "workspace:7"\n'
                            "  }\n"
                            "}\n"
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:9\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:10\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "identify"])
            self.assertEqual(rt.process_runner.calls[2], ["cmux", "new-workspace", "--cwd", str(repo.resolve())])
            self.assertEqual(rt.process_runner.calls[3], ["cmux", "current-workspace"])
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "rename-workspace", "--workspace", "workspace:9", "envctl implementation"])
            self.assertEqual(rt.process_runner.calls[5], ["cmux", "list-pane-surfaces", "--workspace", "workspace:9"])
            self.assertNotIn(["cmux", "new-surface", "--workspace", "workspace:9"], rt.process_runner.calls)

    def test_cmux_workspace_alias_resolves_workspace_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "CMUX_WORKSPACE": "envctl",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-surface", "--workspace", "workspace:1"])

    def test_created_named_workspace_reuses_single_starter_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "brand-new-workspace",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:3\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-workspace", "--cwd", str(repo.resolve())])
            self.assertEqual(rt.process_runner.calls[2], ["cmux", "current-workspace"])
            self.assertEqual(
                rt.process_runner.calls[3],
                ["cmux", "rename-workspace", "--workspace", "workspace:3", "brand-new-workspace"],
            )
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "list-pane-surfaces", "--workspace", "workspace:3"])
            self.assertNotIn(["cmux", "new-surface", "--workspace", "workspace:3"], rt.process_runner.calls)

    def test_created_workspace_emits_probe_and_reused_surface_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "brand-new-workspace",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:3\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            probe_events = self._events(rt, "planning.agent_launch.workspace_surface_probe")
            self.assertEqual(
                probe_events,
                [
                    {
                        "event": "planning.agent_launch.workspace_surface_probe",
                        "workspace_id": "workspace:3",
                        "result": "single",
                        "surface_count": 1,
                        "surface_id": "surface:44",
                    }
                ],
            )
            self.assertEqual(self._events(rt, "planning.agent_launch.surface_fallback"), [])
            self.assertEqual(
                self._events(rt, "planning.agent_launch.surface_created"),
                [
                    {
                        "event": "planning.agent_launch.surface_created",
                        "workspace_id": "workspace:3",
                        "surface_id": "surface:44",
                        "worktree": "feature-a-1",
                        "source": "starter_reused",
                    }
                ],
            )

    def test_created_workspace_falls_back_to_new_surface_when_starter_probe_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "brand-new-workspace",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:3\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\nsurface:45\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:46\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "list-pane-surfaces", "--workspace", "workspace:3"])
            self.assertEqual(rt.process_runner.calls[5], ["cmux", "new-surface", "--workspace", "workspace:3"])

    def test_created_workspace_emits_probe_and_fallback_events_when_probe_is_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "brand-new-workspace",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:1  envctl  [selected]\n  workspace:2  supportopia\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:3\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:44\nsurface:45\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:46\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workspace_surface_probe"),
                [
                    {
                        "event": "planning.agent_launch.workspace_surface_probe",
                        "workspace_id": "workspace:3",
                        "result": "ambiguous",
                        "surface_count": 2,
                    }
                ],
            )
            self.assertEqual(
                self._events(rt, "planning.agent_launch.surface_fallback"),
                [
                    {
                        "event": "planning.agent_launch.surface_fallback",
                        "workspace_id": "workspace:3",
                        "reason": "ambiguous",
                    }
                ],
            )
            self.assertEqual(
                self._events(rt, "planning.agent_launch.surface_created"),
                [
                    {
                        "event": "planning.agent_launch.surface_created",
                        "workspace_id": "workspace:3",
                        "surface_id": "surface:46",
                        "worktree": "feature-a-1",
                        "source": "new_surface",
                    }
                ],
            )

    def test_existing_workspace_still_creates_new_surface(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CMUX_WORKSPACE_ID": "workspace:4",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:4  envctl  [selected]\n  workspace:9  envctl implementation\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:77\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-surface", "--workspace", "workspace:9"])

    def test_existing_workspace_emits_new_surface_event_without_probe_or_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "CMUX_WORKSPACE_ID": "workspace:4",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:4  envctl  [selected]\n  workspace:9  envctl implementation\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:77\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._start_background_surface_bootstrap", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(self._events(rt, "planning.agent_launch.workspace_surface_probe"), [])
            self.assertEqual(self._events(rt, "planning.agent_launch.surface_fallback"), [])
            self.assertEqual(
                self._events(rt, "planning.agent_launch.surface_created"),
                [
                    {
                        "event": "planning.agent_launch.surface_created",
                        "workspace_id": "workspace:9",
                        "surface_id": "surface:77",
                        "worktree": "feature-a-1",
                        "source": "new_surface",
                    }
                ],
            )

    def test_review_launch_uses_reviews_workspace_and_repo_root_for_codex_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "feature-a" / "1"
            review_bundle = repo / "runtime" / "review" / "all.md"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            project_root.mkdir(parents=True, exist_ok=True)
            review_bundle.parent.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            review_bundle.write_text("# review\n", encoding="utf-8")
            original_plan.write_text("# Original plan\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/feature-a.md"}) + "\n",
                encoding="utf-8",
            )
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "CMUX_WORKSPACE_ID": "workspace:4",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["cmux"],
                        returncode=0,
                        stdout="* workspace:4  envctl  [selected]\n  workspace:8  envctl implementation\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="workspace:10\n", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:12\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_prompt_picker_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_prompt_submit_ready", return_value=None),
            ):
                _ImmediateThread.created = []
                result = launch_support.launch_review_agent_terminal(
                    rt,
                    repo_root=repo,
                    project_name="feature-a-1",
                    project_root=project_root,
                    review_bundle_path=review_bundle,
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "list-workspaces"])
            self.assertEqual(rt.process_runner.calls[1], ["cmux", "new-workspace", "--cwd", str(repo.resolve())])
            self.assertEqual(rt.process_runner.calls[2], ["cmux", "rename-workspace", "--workspace", "workspace:10", "envctl reviews"])
            self.assertEqual(rt.process_runner.calls[3], ["cmux", "list-pane-surfaces", "--workspace", "workspace:10"])
            self.assertEqual(rt.process_runner.calls[4], ["cmux", "new-surface", "--workspace", "workspace:10"])
            self.assertIn(
                ["cmux", "send", "--workspace", "workspace:10", "--surface", "surface:12", f"cd {repo}"],
                rt.process_runner.calls,
            )
            self.assertNotIn(
                ["cmux", "send", "--workspace", "workspace:10", "--surface", "surface:12", f"cd {project_root}"],
                rt.process_runner.calls,
            )
            review_prompt_calls = [
                call
                for call in rt.process_runner.calls
                if call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-12"]
            ]
            self.assertEqual(len(review_prompt_calls), 1)
            self.assertIn("current local repo directory is the unedited baseline", str(review_prompt_calls[0][-1]))
            self.assertIn(f'Review bundle: "{review_bundle}"', str(review_prompt_calls[0][-1]))
            self.assertIn(f'Worktree directory: "{project_root}"', str(review_prompt_calls[0][-1]))
            self.assertIn(f'Original plan file: "{original_plan.resolve()}"', str(review_prompt_calls[0][-1]))
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-12", "--workspace", "workspace:10", "--surface", "surface:12"],
                rt.process_runner.calls,
            )

    def test_review_launch_honors_explicit_workspace_override_and_opencode_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "feature-a" / "1"
            review_bundle = repo / "runtime" / "review" / "all.md"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            project_root.mkdir(parents=True, exist_ok=True)
            review_bundle.parent.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            review_bundle.write_text("# review\n", encoding="utf-8")
            original_plan.write_text("# Current plan\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/feature-a.md"}) + "\n",
                encoding="utf-8",
            )
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:9",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:15\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_prompt_picker_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_prompt_submit_ready", return_value=None),
            ):
                _ImmediateThread.created = []
                result = launch_support.launch_review_agent_terminal(
                    rt,
                    repo_root=repo,
                    project_name="feature-a-1",
                    project_root=project_root,
                    review_bundle_path=review_bundle,
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(rt.process_runner.calls[0], ["cmux", "new-surface", "--workspace", "workspace:9"])
            self.assertNotIn(["cmux", "list-workspaces"], rt.process_runner.calls)
            self.assertIn(
                [
                    "cmux",
                    "send",
                    "--workspace",
                    "workspace:9",
                    "--surface",
                    "surface:15",
                    "/review_worktree_imp Project: feature-a-1\n"
                    f'Review bundle: "{review_bundle}"\n'
                    f'Worktree directory: "{project_root}"\n'
                    f'Original plan file: "{original_plan.resolve()}"',
                ],
                rt.process_runner.calls,
            )

    def test_review_launch_uses_direct_prompt_submission_for_opencode_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            project_root = repo / "trees" / "feature-a" / "1"
            review_bundle = repo / "runtime" / "review" / "all.md"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            installed_prompt = Path(tmpdir) / ".config" / "opencode" / "commands" / "review_worktree_imp.md"
            project_root.mkdir(parents=True, exist_ok=True)
            review_bundle.parent.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            installed_prompt.parent.mkdir(parents=True, exist_ok=True)
            review_bundle.write_text("# review\n", encoding="utf-8")
            original_plan.write_text("# Current plan\n", encoding="utf-8")
            installed_prompt.write_text("Review prompt body\n$ARGUMENTS\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/feature-a.md"}) + "\n",
                encoding="utf-8",
            )
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "HOME": tmpdir,
                    "ENVCTL_PLAN_AGENT_CLI": "opencode",
                    "ENVCTL_PLAN_AGENT_DIRECT_PROMPT": "true",
                    "ENVCTL_PLAN_AGENT_ULW_LOOP_PREFIX": "true",
                    "ENVCTL_PLAN_AGENT_APPEND_ULW": "true",
                    "ENVCTL_PLAN_AGENT_CMUX_WORKSPACE": "workspace:9",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["cmux"], returncode=0, stdout="surface:15\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent_launch_support.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent_launch_support.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent_launch_support._wait_for_cli_ready", return_value=None),
            ):
                _ImmediateThread.created = []
                result = launch_support.launch_review_agent_terminal(
                    rt,
                    repo_root=repo,
                    project_name="feature-a-1",
                    project_root=project_root,
                    review_bundle_path=review_bundle,
                )

            self.assertEqual(result.status, "launched")
            direct_prompt_calls = [
                call
                for call in rt.process_runner.calls
                if call[:4] == ["cmux", "set-buffer", "--name", "envctl-surface-15"]
            ]
            self.assertEqual(len(direct_prompt_calls), 1)
            self.assertTrue(str(direct_prompt_calls[0][-1]).startswith("/ulw_loop Review prompt body"))
            self.assertIn(f'Review bundle: "{review_bundle}"', str(direct_prompt_calls[0][-1]))
            self.assertIn(f'Original plan file: "{original_plan.resolve()}" ulw', str(direct_prompt_calls[0][-1]))
            self.assertTrue(str(direct_prompt_calls[0][-1]).rstrip().endswith("ulw"))
            self.assertIn(
                ["cmux", "paste-buffer", "--name", "envctl-surface-15", "--workspace", "workspace:9", "--surface", "surface:15"],
                rt.process_runner.calls,
            )

    def test_review_launch_resolves_original_plan_file_from_worktree_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "feature-a" / "1"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            project_root.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            original_plan.write_text("# first plan\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/feature-a.md"}) + "\n",
                encoding="utf-8",
            )
            original_plan_path = getattr(launch_support, "_review_original_plan_path")(
                "feature-a-1",
                project_root,
                repo_root=repo,
            )

            self.assertEqual(original_plan_path, original_plan.resolve())

    def test_review_launch_returns_none_when_original_plan_file_cannot_be_resolved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "feature-a" / "1"
            project_root.mkdir(parents=True, exist_ok=True)

            original_plan_path = getattr(launch_support, "_review_original_plan_path")(
                "feature-a-1",
                project_root,
                repo_root=repo,
            )

            self.assertIsNone(original_plan_path)

    def test_review_launch_can_infer_original_plan_file_without_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "implementations_task" / "1"
            original_plan = repo / "todo" / "done" / "implementations" / "task.md"
            project_root.mkdir(parents=True, exist_ok=True)
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            original_plan.write_text("# done plan\n", encoding="utf-8")

            original_plan_path = getattr(launch_support, "_review_original_plan_path")(
                "implementations_task-1",
                project_root,
                repo_root=repo,
            )

            self.assertEqual(original_plan_path, original_plan.resolve())

    def test_review_launch_prefers_active_plan_over_archived_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "features_task"
            active_plan = repo / "todo" / "plans" / "features" / "task.md"
            archived_plan = repo / "todo" / "done" / "features" / "task.md"
            project_root.mkdir(parents=True, exist_ok=True)
            active_plan.parent.mkdir(parents=True, exist_ok=True)
            archived_plan.parent.mkdir(parents=True, exist_ok=True)
            active_plan.write_text("# active plan\n", encoding="utf-8")
            archived_plan.write_text("# archived plan\n", encoding="utf-8")

            original_plan_path = getattr(launch_support, "_review_original_plan_path")(
                "features_task",
                project_root,
                repo_root=repo,
            )

            self.assertEqual(original_plan_path, active_plan.resolve())


if __name__ == "__main__":
    unittest.main()
