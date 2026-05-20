from __future__ import annotations

import json
import os
import shlex
import sqlite3
import subprocess
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from importlib import resources
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

from envctl_engine.config import load_config
from envctl_engine.planning import plan_agent_launch_support as launch_support
from envctl_engine.planning.plan_agent import (
    cmux_transport,
    config,
    omx_transport,
    recovery,
    terminal_screen,
    tmux_session,
    tmux_transport,
    workflow,
)
from envctl_engine.planning.plan_agent.models import _WorkspaceLaunchTarget
from envctl_engine.planning.plan_agent_launch_support import CreatedPlanWorktree, launch_plan_agent_terminals
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord

_screen_looks_ready = terminal_screen._screen_looks_ready
_prompt_submit_screen_looks_ready = terminal_screen._prompt_submit_screen_looks_ready
_tab_title_for_worktree = workflow._tab_title_for_worktree
_build_plan_agent_workflow = cast(Any, workflow._build_plan_agent_workflow)
_finalization_instruction_text = cast(Any, workflow._finalization_instruction_text)
_first_cycle_completion_instruction_text = cast(Any, workflow._first_cycle_completion_instruction_text)
_intermediate_cycle_completion_instruction_text = cast(Any, workflow._intermediate_cycle_completion_instruction_text)
_browser_e2e_instruction_text = cast(Any, workflow._browser_e2e_instruction_text)
_pr_review_comments_instruction_text = cast(Any, workflow._pr_review_comments_instruction_text)
_wait_for_codex_queue_ready = cast(Any, cmux_transport._wait_for_codex_queue_ready)
_workflow_step_prompt_text = cast(Any, workflow._workflow_step_prompt_text)
_ensure_tmux_window = cast(Any, tmux_transport._ensure_tmux_window)
_tmux_session_name_for_worktree = cast(Any, tmux_transport._tmux_session_name_for_worktree)
_run_tmux_worktree_bootstrap = cast(Any, tmux_transport._run_tmux_worktree_bootstrap)
_wait_for_tmux_cli_ready = cast(Any, tmux_transport._wait_for_tmux_cli_ready)
_screen_looks_active = cast(Any, terminal_screen._screen_looks_active)


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
        self.state_repository: _StateRepositoryHarness | None = None
        self._plan_agent_events: list[dict[str, object]] = []
        self._persist_events_snapshot_calls = 0

    def _command_exists(self, command: str) -> bool:
        return command in {"cmux", "codex", "omx", "opencode", "script", "superset", "tmux", "zsh"}

    def _emit(self, event: str, **payload: object) -> None:
        self._plan_agent_events.append({"event": event, **payload})

    def _persist_events_snapshot(self) -> None:
        self._persist_events_snapshot_calls += 1


class _StateRepositoryHarness:
    def __init__(self, state: RunState | None) -> None:
        self.state = state

    def load_latest(self, *, mode: str | None = None, strict_mode_match: bool = False) -> RunState | None:
        _ = mode, strict_mode_match
        return self.state


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

    def _superset_host_db(self, home: Path, host_id: str = "host-1") -> Path:
        host_db = home / ".superset" / "host" / host_id / "host.db"
        host_db.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(host_db) as connection:
            connection.execute(
                """
                create table host_agent_configs (
                    id text primary key not null,
                    preset_id text not null,
                    label text not null,
                    command text not null,
                    args_json text default '[]' not null,
                    prompt_transport text not null,
                    prompt_args_json text default '[]' not null,
                    env_json text default '{}' not null,
                    display_order integer not null,
                    created_at integer not null,
                    updated_at integer not null
                )
                """
            )
            connection.execute(
                """
                insert into host_agent_configs
                (id, preset_id, label, command, args_json, prompt_transport, prompt_args_json, env_json, display_order, created_at, updated_at)
                values ('codex-default', 'codex', 'Codex', 'codex', '["--dangerously-bypass-approvals-and-sandbox"]', 'argv', '["--"]', '{}', 0, 1, 1)
                """
            )
            connection.commit()
        return host_db

    def _expected_omx_root(self, worktree: CreatedPlanWorktree) -> Path:
        token = omx_transport._sanitize_omx_tmux_token(worktree.name)
        return Path(worktree.root).resolve() / ".envctl-state" / "omx" / token

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
                    "ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE": "false",
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None) as sleep_mock,
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter()),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
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

    def test_resolve_plan_agent_launch_config_treats_explicit_opencode_as_tmux_launch(self) -> None:
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
                route=parse_route(["--plan", "feature-a", "--opencode"], env={}),
            )
            prereqs = launch_support.plan_agent_launch_prereq_commands(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--opencode"], env={}),
            )

        self.assertEqual(launch_config.transport, "tmux")
        self.assertEqual(launch_config.cli, "opencode")
        self.assertTrue(launch_config.enabled)
        self.assertTrue(launch_config.direct_prompt_enabled)
        self.assertTrue(launch_config.ulw_loop_prefix)
        self.assertEqual(prereqs, ("tmux", "opencode"))

    def test_resolve_preset_submission_text_defaults_ulw_loop_for_explicit_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            prompt_path = Path(tmpdir) / ".config" / "opencode" / "commands" / "implement_task.md"
            repo.mkdir(parents=True, exist_ok=True)
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text("Implement this directly.\n", encoding="utf-8")
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {"HOME": tmpdir},
                route=parse_route(["--plan", "feature-a", "--opencode"], env={}),
            )
            rt = self._runtime(repo, runtime, env={"HOME": tmpdir})

            prompt_text, error = workflow._resolve_preset_submission_text(
                rt,
                launch_config=launch_config,
                cli="opencode",
                preset="implement_task",
            )

        self.assertIsNone(error)
        self.assertEqual(prompt_text, "/ulw-loop Implement this directly.")

    def test_resolve_plan_agent_launch_config_ulw_route_enables_direct_prompt_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_DIRECT_PROMPT": "false",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--ulw"], env={}),
            )

        self.assertTrue(launch_config.direct_prompt_enabled)
        self.assertTrue(launch_config.ulw_loop_prefix)

    def test_create_plan_auto_launch_default_routes_remain_supported(self) -> None:
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

            codex_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {"ENVCTL_PLAN_AGENT_CODEX_CYCLES": "4"},
                route=parse_route(["--plan", "features/example", "--tmux"], env={}),
            )
            codex_workflow = _build_plan_agent_workflow(
                cli=codex_config.cli,
                preset=codex_config.preset,
                codex_cycles=codex_config.codex_cycles,
                direct_prompt_enabled=codex_config.direct_prompt_enabled,
            )

            opencode_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "features/example", "--tmux", "--opencode", "--ulw"], env={}),
            )
            opencode_workflow = _build_plan_agent_workflow(
                cli=opencode_config.cli,
                preset=opencode_config.preset,
                codex_cycles=opencode_config.codex_cycles,
                direct_prompt_enabled=opencode_config.direct_prompt_enabled,
            )

            omx_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {"ENVCTL_PLAN_AGENT_CODEX_CYCLES": "4"},
                route=parse_route(["--plan", "features/example", "--omx", "--ultragoal"], env={}),
            )
            omx_workflow = _build_plan_agent_workflow(
                cli=omx_config.cli,
                preset=omx_config.preset,
                codex_cycles=omx_config.codex_cycles,
                direct_prompt_enabled=omx_config.direct_prompt_enabled,
            )

        self.assertEqual(codex_config.transport, "tmux")
        self.assertEqual(codex_config.cli, "codex")
        self.assertEqual(codex_config.preset, "implement_task")
        self.assertEqual(codex_config.codex_cycles, 4)
        self.assertTrue(codex_config.pr_review_comments_followup_enable)
        self.assertEqual(codex_workflow.mode, "codex_cycles")
        self.assertEqual(codex_workflow.codex_cycles, 4)

        self.assertEqual(opencode_config.transport, "tmux")
        self.assertEqual(opencode_config.cli, "opencode")
        self.assertTrue(opencode_config.direct_prompt_enabled)
        self.assertTrue(opencode_config.ulw_loop_prefix)
        self.assertEqual(opencode_workflow.mode, "single_prompt")

        self.assertEqual(omx_config.transport, "omx")
        self.assertEqual(omx_config.cli, "codex")
        self.assertEqual(omx_config.omx_workflow, "ultragoal")
        self.assertEqual(omx_config.codex_cycles, 4)
        self.assertIsNone(omx_config.codex_cycles_warning)
        self.assertTrue(omx_config.pr_review_comments_followup_enable)
        self.assertEqual(omx_workflow.mode, "codex_cycles")

    def test_resolve_plan_agent_launch_config_goal_defaults_and_route_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime)})

            codex_default = launch_support.resolve_plan_agent_launch_config(
                config, {}, route=parse_route(["--plan", "feature-a", "--tmux"], env={})
            )
            opencode_default = launch_support.resolve_plan_agent_launch_config(
                config, {}, route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={})
            )
            disabled = launch_support.resolve_plan_agent_launch_config(
                config, {}, route=parse_route(["--plan", "feature-a", "--tmux", "--no-goal", "--goal"], env={})
            )
            enabled_by_route = launch_support.resolve_plan_agent_launch_config(
                load_config({
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE": "false",
                }),
                {},
                route=parse_route(["--plan", "feature-a", "--tmux", "--goal"], env={}),
            )

        self.assertTrue(codex_default.codex_goal_enable)
        self.assertFalse(opencode_default.codex_goal_enable)
        self.assertFalse(disabled.codex_goal_enable)
        self.assertTrue(enabled_by_route.codex_goal_enable)

    def test_omx_goal_then_workflow_then_cycle_queue_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            for workflow_name in ("ralph", "ultragoal"):
                with self.subTest(workflow_name=workflow_name):
                    rt = self._runtime(repo, runtime_dir)
                    worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="features/a.md")
                    launch_config = launch_support.PlanAgentLaunchConfig(
                        enabled=True,
                        transport="omx",
                        cli="codex",
                        cli_command="codex",
                        preset="implement_task",
                        codex_cycles=1,
                        codex_cycles_warning=None,
                        shell="zsh",
                        require_cmux_context=True,
                        cmux_workspace="",
                        direct_prompt_enabled=False,
                        ulw_loop_prefix=False,
                        ulw_suffix=False,
                        omx_workflow=workflow_name,
                        codex_goal_enable=True,
                    )
                    workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=1)
                    submitted: list[str] = []
                    queued: list[str] = []

                    def fake_submit(*_args, prompt_text, **_kwargs):  # noqa: ANN202, ANN001
                        submitted.append(prompt_text)
                        return None

                    def fake_queue(*_args, queued_steps, **_kwargs):  # noqa: ANN202, ANN001
                        queued.extend(step.kind for step in queued_steps)
                        return None

                    with (
                        patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                        patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_codex_goal", return_value=None),
                        patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step", side_effect=fake_submit),
                        patch("envctl_engine.planning.plan_agent.tmux_transport._queue_tmux_codex_workflow_steps", side_effect=fake_queue),
                        patch("envctl_engine.planning.plan_agent.tmux_transport._workflow_step_prompt_text", side_effect=lambda *_args, step, **_kwargs: (f"resolved::{step.kind}::{step.text}", None)),
                    ):
                        error = tmux_transport._run_tmux_existing_session_workflow(
                            rt,
                            session_name="session",
                            window_name="window",
                            launch_config=launch_config,
                            workflow=workflow,
                            worktree=worktree,
                        )

                    self.assertIsNone(error)
                    self.assertEqual(len(submitted), 1)
                    self.assertTrue(submitted[0].startswith(f"${workflow_name}"))
                    self.assertEqual(queued, ["queue_direct_prompt", "queue_message", "queue_message"])

    def test_omx_goal_fallback_still_submits_ralph_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime_dir)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="features/a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="omx",
                cli="codex",
                cli_command="codex",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
                omx_workflow="ralph",
                codex_goal_enable=True,
            )
            workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=0)
            submitted: list[str] = []

            with (
                patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_codex_goal", return_value="codex_goal_ready_timeout"),
                patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step", side_effect=lambda *_args, prompt_text, **_kwargs: submitted.append(prompt_text) or None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._queue_tmux_codex_workflow_steps", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._workflow_step_prompt_text", side_effect=lambda *_args, step, **_kwargs: (f"resolved::{step.kind}::{step.text}", None)),
            ):
                error = tmux_transport._run_tmux_existing_session_workflow(
                    rt,
                    session_name="session",
                    window_name="window",
                    launch_config=launch_config,
                    workflow=workflow,
                    worktree=worktree,
                )

        self.assertIsNone(error)
        self.assertTrue(submitted[0].startswith("$ralph"))
        self.assertEqual(
            self._events(rt, "planning.agent_launch.codex_goal_fallback")[0]["reason"],
            "codex_goal_ready_timeout",
        )

    def test_resolve_plan_agent_launch_config_allows_pr_review_comment_followup_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text(
                "ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE=false\n",
                encoding="utf-8",
            )
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "features/example", "--omx", "--ralph"], env={}),
            )
            workflow = _build_plan_agent_workflow(
                cli=launch_config.cli,
                preset=launch_config.preset,
                codex_cycles=launch_config.codex_cycles,
                direct_prompt_enabled=launch_config.direct_prompt_enabled,
                pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
            )

        self.assertFalse(launch_config.pr_review_comments_followup_enable)
        self.assertNotIn(_pr_review_comments_instruction_text(), [step.text for step in workflow.steps])

    def test_resolve_plan_agent_launch_config_allows_browser_e2e_followup_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text(
                "ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=false\n",
                encoding="utf-8",
            )
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "features/example"], env={}),
            )
            workflow = _build_plan_agent_workflow(
                cli=launch_config.cli,
                preset=launch_config.preset,
                codex_cycles=launch_config.codex_cycles,
                direct_prompt_enabled=launch_config.direct_prompt_enabled,
                browser_e2e_followup_enable=launch_config.browser_e2e_followup_enable,
                pr_review_comments_followup_enable=launch_config.pr_review_comments_followup_enable,
            )

        self.assertFalse(launch_config.browser_e2e_followup_enable)
        self.assertNotIn(_browser_e2e_instruction_text(), [step.text for step in workflow.steps])
        self.assertIn(_pr_review_comments_instruction_text(), [step.text for step in workflow.steps])

    def test_launch_plan_agent_terminals_rejects_ulw_without_tmux_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a", "--tmux", "--codex", "--ulw"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
            )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "unsupported_ulw_flag")

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

    def test_resolve_plan_agent_launch_config_records_omx_workflow_flag(self) -> None:
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

            for token, workflow_name in (("--ultragoal", "ultragoal"), ("--ralph", "ralph"), ("--team", "team")):
                with self.subTest(token=token):
                    launch_config = launch_support.resolve_plan_agent_launch_config(
                        config,
                        {},
                        route=parse_route(["--plan", "feature-a", "--omx", token], env={}),
                    )

                    self.assertEqual(launch_config.transport, "omx")
                    self.assertEqual(launch_config.cli, "codex")
                    self.assertEqual(launch_config.omx_workflow, workflow_name)
                    self.assertEqual(launch_config.codex_cycles, 2)

    def test_resolve_plan_agent_launch_config_keeps_cycles_for_plain_omx(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "3",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--omx"], env={}),
            )

        self.assertEqual(launch_config.transport, "omx")
        self.assertEqual(launch_config.cli, "codex")
        self.assertEqual(launch_config.codex_cycles, 3)
        self.assertIsNone(launch_config.codex_cycles_warning)

    def test_resolve_plan_agent_launch_config_keeps_cycles_for_omx_workflows(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "3",
                }
            )

            for token, workflow_name in (("--ultragoal", "ultragoal"), ("--ralph", "ralph"), ("--team", "team")):
                with self.subTest(token=token):
                    launch_config = launch_support.resolve_plan_agent_launch_config(
                        config,
                        {},
                        route=parse_route(["--plan", "feature-a", "--omx", token], env={}),
                    )
                    workflow = _build_plan_agent_workflow(
                        cli=launch_config.cli,
                        preset=launch_config.preset,
                        codex_cycles=launch_config.codex_cycles,
                        direct_prompt_enabled=launch_config.direct_prompt_enabled,
                    )

                    self.assertEqual(launch_config.omx_workflow, workflow_name)
                    self.assertEqual(launch_config.codex_cycles, 3)
                    self.assertIsNone(launch_config.codex_cycles_warning)
                    self.assertEqual(workflow.mode, "codex_cycles")
                    self.assertEqual(workflow.codex_cycles, 3)
                    self.assertEqual(len(workflow.steps), 10)
                    self.assertEqual(workflow.steps[1].text, _first_cycle_completion_instruction_text())
                    self.assertEqual(workflow.steps[-2].text, _browser_e2e_instruction_text())
                    self.assertEqual(workflow.steps[-1].text, _pr_review_comments_instruction_text())

    def test_resolve_plan_agent_launch_config_forces_codex_for_omx_when_env_prefers_opencode(self) -> None:
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
                route=parse_route(["--plan", "feature-a", "--omx"], env={}),
            )

        self.assertEqual(launch_config.transport, "omx")
        self.assertEqual(launch_config.cli, "codex")
        self.assertEqual(launch_config.cli_command, "codex --dangerously-bypass-approvals-and-sandbox")

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

    def test_resolve_plan_agent_launch_config_allows_disabling_codex_yolo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_CODEX_YOLO": "false",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config,
                {},
                route=parse_route(["--plan", "feature-a", "--tmux", "--codex"], env={}),
            )

        self.assertEqual(launch_config.transport, "tmux")
        self.assertEqual(launch_config.cli, "codex")
        self.assertEqual(launch_config.cli_command, "codex")
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
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="envctl-test-session",
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "envctl-test-session"),
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._resolve_tmux_attach_target", return_value=attach_target),
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
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach", "-t", expected_attach_session))
            expected_session_name = next(call[3] for call in rt.process_runner.calls if call[:3] == ["tmux", "has-session", "-t"])
            self.assertIn(["tmux", "has-session", "-t", expected_session_name], rt.process_runner.calls)
            self.assertEqual(expected_session_name, expected_attach_session)
            launch_calls = [call for call in rt.process_runner.calls if call[:2] in (["tmux", "new-session"], ["tmux", "new-window"])]
            self.assertTrue(launch_calls)
            self.assertTrue(any(call[0:5] == ["tmux", "new-session", "-d", "-s", expected_session_name] or call[0:5] == ["tmux", "new-window", "-d", "-t", expected_session_name] for call in launch_calls))
            self.assertIn(["tmux", "set-option", "-t", expected_session_name, "mouse", "on"], rt.process_runner.calls)
            self.assertIn(["tmux", "send-keys", "-t", f"{expected_session_name}:feature-a-1", "-l", f"cd {shlex.quote(str(repo))}"], rt.process_runner.calls)
            self.assertIn(["tmux", "send-keys", "-t", f"{expected_session_name}:feature-a-1", "Enter"], rt.process_runner.calls)
            self.assertIn(["tmux", "send-keys", "-t", f"{expected_session_name}:feature-a-1", "-l", "opencode"], rt.process_runner.calls)

    def test_tmux_opencode_launch_fails_when_cli_never_becomes_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=1, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=1, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="feature-a-1\n", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                ]
            )

            with (
                redirect_stdout(StringIO()) as buffer,
                patch(
                    "envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready",
                    return_value=launch_support.AiCliReadyResult(
                        ready=False,
                        reason="opencode_ready_timeout",
                        screen_excerpt="zsh: command not found: opencode",
                    ),
                ),
                patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step", return_value=None) as submit_mock,
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
                    created_worktrees=(
                        CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="feature-a.md"),
                    ),
                )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "launch_failed")
        self.assertEqual(len(result.outcomes), 1)
        self.assertEqual(result.outcomes[0].status, "failed")
        self.assertIn("opencode_ready_timeout", str(result.outcomes[0].reason))
        self.assertIn("zsh: command not found: opencode", str(result.outcomes[0].reason))
        self.assertIn("opencode_ready_timeout", buffer.getvalue())
        submit_mock.assert_not_called()

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
                patch("envctl_engine.planning.plan_agent.tmux_transport._launch_tmux_cli_bootstrap_commands", return_value=[None]),
                patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._workflow_step_prompt_text", side_effect=resolve_step),
                patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_prompt", return_value=None) as send_prompt_mock,
                patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_text", return_value=None) as send_text_mock,
                patch("envctl_engine.planning.plan_agent.tmux_transport._queue_tmux_codex_message", return_value=True) as queue_mock,
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
            self.assertEqual(send_text_mock.call_count, 0)
            self.assertEqual(send_prompt_mock.call_count, 6)
            self.assertEqual(queue_mock.call_count, 6)
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
                        "queued_steps": 6,
                        "queued_steps_confirmed": 6,
                        "transport": "tmux",
                    }
                ],
            )

    def test_tmux_codex_workflow_queue_failure_emits_fallback_with_step_context(self) -> None:
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
                codex_cycles=1,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
            )
            workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=1)

            def resolve_step(*_args, step, **_kwargs):
                return (f"resolved::{step.kind}::{step.text}", None)

            with (
                patch("envctl_engine.planning.plan_agent.tmux_transport._launch_tmux_cli_bootstrap_commands", return_value=[None]),
                patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._workflow_step_prompt_text", side_effect=resolve_step),
                patch("envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_prompt", return_value=None),
                patch("envctl_engine.planning.plan_agent.tmux_transport._queue_tmux_codex_message", return_value=False),
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
            expected = {
                "session_name": "envctl-test-session",
                "window_name": "feature-a-1",
                "worktree": "feature-a-1",
                "cli": "codex",
                "workflow_mode": "codex_cycles",
                "codex_cycles": 1,
                "reason": "queue_not_ready",
                "transport": "tmux",
                "queue_failed_step_index": 0,
                "queue_failed_step_kind": "queue_direct_prompt",
            }
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_queue_failed"),
                [{"event": "planning.agent_launch.workflow_queue_failed", **expected}],
            )
            self.assertEqual(
                self._events(rt, "planning.agent_launch.workflow_fallback"),
                [{"event": "planning.agent_launch.workflow_fallback", **expected}],
            )

    def test_omx_launch_spawns_managed_session_and_bootstraps_existing_tmux_session(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            provenance_path = repo / ".envctl-state" / "worktree-provenance.json"
            provenance_path.parent.mkdir(parents=True, exist_ok=True)
            provenance_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "plan_file": "a.md",
                        "created_for_fresh_ai_launch": True,
                        "fresh_ai_launch_status": "launching",
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                },
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-feature-session",
                window_name="%42",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-feature-session"),
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None) as spawn_mock,
                patch("envctl_engine.planning.plan_agent.omx_transport._wait_for_omx_attach_target", return_value=attach_target) as wait_mock,
                patch("envctl_engine.planning.plan_agent.launch._run_tmux_existing_session_workflow", return_value=None) as workflow_mock,
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                    created_worktrees=(worktree,),
                )

            self.assertEqual(result.status, "launched")
            spawn_mock.assert_called_once()
            wait_mock.assert_called_once()
            workflow_mock.assert_called_once()
            self.assertIsNotNone(result.attach_target)
            assert result.attach_target is not None
            self.assertEqual(result.attach_target.session_name, "omx-feature-session")
            self.assertEqual(result.attach_target.window_name, "%42")
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach", "-t", "omx-feature-session"))
            provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
            self.assertEqual(provenance["fresh_ai_launch_status"], "launched")
            self.assertEqual(provenance["launch_transport"], "omx")
            self.assertEqual(provenance["session_name"], "omx-feature-session")

    def test_omx_launch_fails_when_attach_target_disappears_after_workflow_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-feature-session",
                window_name="%42",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-feature-session"),
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._wait_for_omx_attach_target", return_value=attach_target),
                patch("envctl_engine.planning.plan_agent.launch._run_tmux_existing_session_workflow", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=False),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                    created_worktrees=(worktree,),
                )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "launch_failed")
            self.assertIsNone(result.attach_target)
            self.assertEqual(result.outcomes[0].status, "failed")
            self.assertEqual(result.outcomes[0].reason, "omx_attach_target_stale")
            self.assertEqual(
                self._events(rt, "planning.agent_launch.attach_validation.failed")[-1]["reason"],
                "omx_attach_target_stale",
            )

    def test_omx_launch_validation_failure_prints_native_recovery_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-feature-session",
                window_name="%42",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-feature-session"),
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._wait_for_omx_attach_target", return_value=attach_target),
                patch("envctl_engine.planning.plan_agent.launch._run_tmux_existing_session_workflow", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    result = launch_plan_agent_terminals(
                        rt,
                        route=parse_route(
                            ["--plan", "feature-a", "--omx", "--codex", "--ralph", "--entire-system", "--headless"],
                            env={},
                        ),
                        created_worktrees=(worktree,),
                    )

            self.assertEqual(result.status, "failed")
            rendered = out.getvalue()
            self.assertIn("recovery: ENVCTL_PLAN_AGENT_CODEX_CYCLES=2", rendered)
            self.assertIn(f"ENVCTL_USE_REPO_WRAPPER=1 {repo / 'bin' / 'envctl'} --plan feature-a --tmux", rendered)
            self.assertIn("--codex", rendered)
            self.assertIn("--entire-system", rendered)
            self.assertIn("--headless", rendered)
            self.assertIn("--tmux-new-session", rendered)
            self.assertNotIn("--omx", rendered)
            self.assertNotIn("--ralph", rendered)
            self.assertNotIn("--ultragoal", rendered)
            self.assertNotIn("--team", rendered)

    def test_omx_launch_fails_when_worktree_removed_after_attach_target_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-feature-session",
                window_name="%42",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-feature-session"),
            )

            def _queue_then_remove_worktree(*_args: object, **_kwargs: object) -> None:
                repo.rmdir()
                return None

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._wait_for_omx_attach_target", return_value=attach_target),
                patch("envctl_engine.planning.plan_agent.launch._run_tmux_existing_session_workflow", side_effect=_queue_then_remove_worktree),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%42"),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                    created_worktrees=(worktree,),
                )

            self.assertEqual(result.status, "failed")
            self.assertIsNone(result.attach_target)
            self.assertEqual(result.outcomes[0].reason, "worktree_removed_after_launch")

    def test_omx_launch_records_late_spawn_exit_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"})
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-feature-session",
                window_name="%42",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-feature-session"),
            )

            class _ExitedProcess:
                pid = 4242
                args = ["script", "-qfc", "omx --tmux", "/dev/null"]

                def poll(self) -> int:
                    return 7

            rt._omx_spawn_processes = [_ExitedProcess()]  # type: ignore[attr-defined]

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._wait_for_omx_attach_target", return_value=attach_target),
                patch("envctl_engine.planning.plan_agent.launch._run_tmux_existing_session_workflow", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%42"),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                    created_worktrees=(worktree,),
                )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.outcomes[0].reason, "omx_session_exited")
            exited_events = self._events(rt, "planning.agent_launch.omx_spawn.exited_early")
            self.assertEqual(exited_events[-1]["pid"], 4242)
            self.assertEqual(exited_events[-1]["returncode"], 7)
            self.assertEqual(exited_events[-1]["command"], ["script", "-qfc", "omx --tmux", "/dev/null"])
            self.assertEqual(exited_events[-1]["worktree"], "feature-a-1")
            self.assertEqual(exited_events[-1]["worktree_root"], str(repo.resolve()))
            self.assertEqual(exited_events[-1]["omx_root"], str(self._expected_omx_root(worktree)))

    def test_validate_omx_attach_target_accepts_current_payload_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            omx_root = self._expected_omx_root(worktree)
            state_path = omx_root / ".omx" / "state" / "session.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-abc123",
                        "native_session_id": "omx-native-session",
                        "cwd": str(repo),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-native-session",
                window_name="%42",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-native-session"),
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_display_message_succeeds", return_value=(True, "%42")),
            ):
                validation = launch_support.validate_plan_agent_attach_target(
                    rt,
                    attach_target,
                    worktree=worktree,
                    transport="omx",
                    phase="post_workflow_queue",
                )

            self.assertTrue(validation.ok)
            self.assertEqual(validation.reason, "ok")

    def test_validate_omx_attach_target_fails_when_current_payload_points_elsewhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            omx_root = self._expected_omx_root(worktree)
            state_path = omx_root / ".omx" / "state" / "session.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-abc123",
                        "native_session_id": "omx-current-session",
                        "cwd": str(repo),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-stale-session",
                window_name="%42",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-stale-session"),
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_display_message_succeeds", return_value=(True, "%42")),
            ):
                validation = launch_support.validate_plan_agent_attach_target(
                    rt,
                    attach_target,
                    worktree=worktree,
                    transport="omx",
                    phase="post_workflow_queue",
                )

        self.assertFalse(validation.ok)
        self.assertEqual(validation.reason, "omx_attach_target_stale")
        failed = self._events(rt, "planning.agent_launch.attach_validation.failed")[-1]
        self.assertEqual(failed["reason"], "omx_attach_target_stale")
        candidates = cast(list[str], failed["omx_session_candidates"])
        self.assertIn("omx-current-session", candidates)
        self.assertNotIn("omx-stale-session", candidates)

    def test_validate_omx_attach_target_ignores_wrong_worktree_payload_for_current_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            other_repo = Path(tmpdir) / "other"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            other_repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            omx_root = self._expected_omx_root(worktree)
            state_path = omx_root / ".omx" / "state" / "session.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-abc123",
                        "native_session_id": "omx-wrong-worktree-session",
                        "cwd": str(other_repo),
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-wrong-worktree-session",
                window_name="%42",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-wrong-worktree-session"),
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_display_message_succeeds", return_value=(True, "%42")),
            ):
                validation = launch_support.validate_plan_agent_attach_target(
                    rt,
                    attach_target,
                    worktree=worktree,
                    transport="omx",
                    phase="post_workflow_queue",
                )

            self.assertFalse(validation.ok)
            self.assertEqual(validation.reason, "omx_attach_target_stale")

    def test_validate_omx_attach_target_falls_back_when_no_payload_records_exist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-pane-discovered-session",
                window_name="%42",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-pane-discovered-session"),
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_display_message_succeeds", return_value=(True, "%42")),
            ):
                validation = launch_support.validate_plan_agent_attach_target(
                    rt,
                    attach_target,
                    worktree=worktree,
                    transport="omx",
                    phase="post_workflow_queue",
                )

            self.assertTrue(validation.ok)
            self.assertEqual(validation.reason, "ok")

    def test_omx_workflow_launch_wraps_initial_prompt_with_workflow_keyword(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            for workflow_name in ("ultragoal", "ralph", "team"):
                with self.subTest(workflow_name=workflow_name):
                    rt = self._runtime(repo, runtime)
                    worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
                    launch_config = launch_support.PlanAgentLaunchConfig(
                        enabled=True,
                        transport="omx",
                        cli="codex",
                        cli_command="codex --dangerously-bypass-approvals-and-sandbox",
                        preset="implement_task",
                        codex_cycles=0,
                        codex_cycles_warning=None,
                        shell="zsh",
                        require_cmux_context=True,
                        cmux_workspace="",
                        direct_prompt_enabled=False,
                        ulw_loop_prefix=False,
                        ulw_suffix=False,
                        omx_workflow=workflow_name,
                        codex_goal_enable=False,
                    )
                    workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=0)
                    submitted_prompts: list[str] = []

                    with (
                        patch("envctl_engine.planning.plan_agent.tmux_transport._wait_for_tmux_cli_ready", return_value=None),
                        patch("envctl_engine.planning.plan_agent.tmux_transport._workflow_step_prompt_text", return_value=("IMPLEMENT TASK BODY", None)),
                        patch(
                            "envctl_engine.planning.plan_agent.tmux_transport._submit_tmux_prompt_workflow_step",
                            side_effect=lambda *_args, prompt_text, **_kwargs: submitted_prompts.append(prompt_text) or None,
                        ),
                    ):
                        error = tmux_transport._run_tmux_existing_session_workflow(
                            rt,
                            session_name="omx-feature-session",
                            window_name="%42",
                            launch_config=launch_config,
                            workflow=workflow,
                            worktree=worktree,
                        )

                    self.assertIsNone(error)
                    self.assertEqual(submitted_prompts, [f"${workflow_name}\n\nIMPLEMENT TASK BODY"])

    def test_omx_workflow_launch_does_not_double_wrap_existing_keyword(self) -> None:
        for workflow_name in ("ultragoal", "ralph", "team"):
            with self.subTest(workflow_name=workflow_name):
                prompt = f"${workflow_name}\n\nIMPLEMENT TASK BODY"
                self.assertEqual(
                    workflow._wrap_omx_initial_prompt_for_workflow(prompt, workflow=workflow_name),
                    prompt,
                )

    def test_omx_new_session_wait_uses_previous_session_id_to_avoid_stale_attach(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            session_path = repo / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text('{"session_id":"old-session","native_session_id":"old-native"}\n', encoding="utf-8")
            attach_target = launch_support.PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-new-session",
                window_name="%42",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-new-session"),
            )

            def _discover_new_session(*_args: object, **_kwargs: object) -> launch_support.PlanAgentAttachTarget:
                session_path.write_text(
                    json.dumps(
                        {
                            "session_id": "new-session",
                            "native_session_id": "omx-new-session",
                            "cwd": str(repo),
                        }
                    )
                    + "\n",
                    encoding="utf-8",
                )
                return attach_target

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None),
                patch(
                    "envctl_engine.planning.plan_agent.omx_transport._wait_for_omx_attach_target",
                    side_effect=_discover_new_session,
                ) as wait_mock,
                patch("envctl_engine.planning.plan_agent.launch._run_tmux_existing_session_workflow", return_value=None),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--tmux-new-session"], env={}),
                    created_worktrees=(worktree,),
                )

            self.assertEqual(result.status, "launched")
            self.assertEqual(wait_mock.call_args.kwargs["previous_session_id"], "old-session")

    def test_missing_launch_commands_includes_script_for_omx(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            launch_config = launch_support.resolve_plan_agent_launch_config(
                cast(Any, rt.config),
                rt.env,
                route=parse_route(["--plan", "feature-a", "--omx"], env={}),
            )

            with patch.object(rt, "_command_exists", side_effect=lambda command: command != "script"):
                missing = config._missing_launch_commands(rt, launch_config)

            self.assertEqual(missing, ["script"])

    def test_omx_spawn_emits_started_event_with_sanitized_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"ENVCTL_SECRET_TOKEN": "do-not-log"})
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="omx",
                cli="codex",
                cli_command="codex --dangerously-bypass-approvals-and-sandbox",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
                omx_workflow="ralph",
            )

            class _RunningPopen:
                pid = 5151

                def __init__(self, _cmd, **_kwargs):  # noqa: ANN001
                    self.stdin = None
                    self.stdout = None
                    self.stderr = None

                def poll(self):
                    return None

            with patch("envctl_engine.planning.plan_agent.omx_transport.subprocess.Popen", _RunningPopen):
                error = omx_transport._spawn_omx_session_for_worktree(
                    rt,
                    launch_config=launch_config,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            event = self._events(rt, "planning.agent_launch.omx_spawn.started")[-1]
            self.assertEqual(event["pid"], 5151)
            self.assertEqual(event["command"], ["omx", "--tmux", "--madmax"])
            self.assertEqual(event["popen_command"], ["script", "-qfc", "omx --tmux --madmax", "/dev/null"])
            self.assertEqual(event["worktree"], "feature-a-1")
            self.assertEqual(event["worktree_root"], str(repo.resolve()))
            self.assertEqual(event["omx_root"], str(self._expected_omx_root(worktree)))
            self.assertEqual(event["transport"], "omx")
            self.assertTrue(event["madmax"])
            self.assertNotIn("env", event)
            self.assertNotIn("do-not-log", json.dumps(event))

    def test_omx_spawn_immediate_failure_emits_bounded_output_and_command_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="omx",
                cli="codex",
                cli_command="codex --dangerously-bypass-approvals-and-sandbox",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
                omx_workflow="",
            )
            long_stdout = "stdout-line\n" + ("x" * 2000)
            long_stderr = "stderr-line\n" + ("y" * 2000)

            class _ExitedPopen:
                pid = 6161
                returncode = 9

                def __init__(self, _cmd, **_kwargs):  # noqa: ANN001
                    pass

                def poll(self):
                    return self.returncode

                def communicate(self, timeout=None):  # noqa: ANN001
                    _ = timeout
                    return long_stdout, long_stderr

            with patch("envctl_engine.planning.plan_agent.omx_transport.subprocess.Popen", _ExitedPopen):
                error = omx_transport._spawn_omx_session_for_worktree(
                    rt,
                    launch_config=launch_config,
                    worktree=worktree,
                )

            self.assertEqual(error, "stderr-line")
            event = self._events(rt, "planning.agent_launch.omx_spawn.failed")[-1]
            self.assertEqual(event["pid"], 6161)
            self.assertEqual(event["returncode"], 9)
            self.assertEqual(event["command"], ["omx", "--tmux", "--madmax"])
            self.assertEqual(event["worktree"], "feature-a-1")
            self.assertEqual(event["omx_root"], str(self._expected_omx_root(worktree)))
            self.assertEqual(event["stdout_excerpt"], long_stdout[:1000])
            self.assertEqual(event["stderr_excerpt"], long_stderr[:1000])
            self.assertNotIn("env", event)

    def test_omx_spawn_sets_deterministic_omx_root_for_madmax_launch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            inherited_root = Path(tmpdir) / "inherited-omx"
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "OMX_ROOT": str(inherited_root),
                    "OMX_STATE_ROOT": str(Path(tmpdir) / "stale-state"),
                    "TMUX": "/tmp/tmux-0/default,1,0",
                    "TMUX_PANE": "%7",
                },
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="omx",
                cli="codex",
                cli_command="codex --dangerously-bypass-approvals-and-sandbox",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
                omx_workflow="ralph",
            )
            popen_calls: list[dict[str, object]] = []

            class _RunningPopen:
                def __init__(self, cmd, **kwargs):  # noqa: ANN001
                    popen_calls.append({"cmd": list(cmd), **kwargs})
                    self.stdin = None
                    self.stdout = None
                    self.stderr = None

                def poll(self):
                    return None

            with patch("envctl_engine.planning.plan_agent.omx_transport.subprocess.Popen", _RunningPopen):
                error = omx_transport._spawn_omx_session_for_worktree(
                    rt,
                    launch_config=launch_config,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            self.assertEqual(popen_calls[0]["cmd"], ["script", "-qfc", "omx --tmux --madmax", "/dev/null"])
            env = cast(dict[str, str], popen_calls[0]["env"])
            self.assertEqual(env["OMX_ROOT"], str(self._expected_omx_root(worktree)))
            self.assertNotEqual(env["OMX_ROOT"], str(inherited_root))
            self.assertEqual(env["OMX_LAUNCH_POLICY"], "detached-tmux")
            self.assertNotIn("TMUX", env)
            self.assertNotIn("TMUX_PANE", env)
            self.assertEqual(
                self._events(rt, "planning.agent_launch.omx_state_root_selected"),
                [
                    {
                        "event": "planning.agent_launch.omx_state_root_selected",
                        "worktree": "feature-a-1",
                        "omx_root": str(self._expected_omx_root(worktree)),
                        "transport": "omx",
                    }
                ],
            )

    def test_omx_wait_discovers_session_from_deterministic_omx_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            omx_root = self._expected_omx_root(worktree)
            session_path = omx_root / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-new-session",
                        "native_session_id": "omx-feature-session",
                        "cwd": str(worktree_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%42"),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="old-session",
                    attach_via="attach-session",
                )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, "omx-feature-session")
            self.assertEqual(attach_target.window_name, "%42")

    def test_omx_wait_rejects_state_for_other_cwd(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            other_root = repo / "trees" / "other" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            other_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            session_path = worktree_root / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-wrong-cwd",
                        "native_session_id": "omx-feature-session",
                        "cwd": str(other_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.02),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%42"),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="",
                    attach_via="attach-session",
                )

            self.assertIsNone(attach_target)

    def test_find_existing_omx_attach_target_reads_deterministic_omx_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            session_path = self._expected_omx_root(worktree) / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-abc123",
                        "native_session_id": "omx-feature-session",
                        "cwd": str(worktree_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%42"),
            ):
                attach_target = omx_transport._find_existing_omx_attach_target(
                    rt,
                    repo_root=repo,
                    created_worktrees=(worktree,),
                )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, "omx-feature-session")
            self.assertEqual(attach_target.window_name, "%42")

    def test_omx_new_session_wait_ignores_previous_session_id_from_selected_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            session_path = self._expected_omx_root(worktree) / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "old-session",
                        "native_session_id": "omx-feature-a-1-main-old",
                        "cwd": str(worktree_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            def _write_new_session(_seconds: float) -> None:
                session_path.write_text(
                    json.dumps(
                        {
                            "session_id": "new-session",
                            "native_session_id": "new-native",
                            "cwd": str(worktree_root.resolve()),
                        }
                    ),
                    encoding="utf-8",
                )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.2),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
                patch("envctl_engine.planning.plan_agent.omx_transport.time.sleep", side_effect=_write_new_session),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%42"),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="old-session",
                    attach_via="attach-session",
                )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, "new-native")

    def test_omx_wait_falls_back_to_legacy_worktree_session_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            session_path = worktree_root / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-legacy",
                        "native_session_id": "omx-legacy-session",
                        "cwd": str(worktree_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_active_pane_id", return_value="%43"),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="",
                    attach_via="attach-session",
                )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, "omx-legacy-session")
            self.assertEqual(attach_target.window_name, "%43")

    def test_omx_wait_falls_back_to_tmux_pane_path_for_matching_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"omx-feature-a-1-main-abc|||ENVCTL_TMUX_PANE|||%77|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                ]
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            session_path = self._expected_omx_root(worktree) / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "omx-abc",
                        "cwd": str(worktree_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=False),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.02),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="",
                    attach_via="attach-session",
                )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, "omx-feature-a-1-main-abc")
            self.assertEqual(attach_target.window_name, "%77")

    def test_omx_wait_falls_back_to_tmux_pane_path_without_session_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"omx-feature-a-1-main-abc|||ENVCTL_TMUX_PANE|||%77|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                ]
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.02),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="",
                    attach_via="attach-session",
                )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, "omx-feature-a-1-main-abc")
            self.assertEqual(attach_target.window_name, "%77")

    def test_omx_new_session_wait_rejects_previous_pane_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"omx-feature-a-1-main-old|||ENVCTL_TMUX_PANE|||%17|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                ]
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")
            session_path = self._expected_omx_root(worktree) / ".omx" / "state" / "session.json"
            session_path.parent.mkdir(parents=True, exist_ok=True)
            session_path.write_text(
                json.dumps(
                    {
                        "session_id": "old-session",
                        "native_session_id": "omx-feature-a-1-main-old",
                        "cwd": str(worktree_root.resolve()),
                    }
                ),
                encoding="utf-8",
            )

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.02),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=False),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="old-session",
                    previous_session_ids=("old-session",),
                    attach_via="attach-session",
                )

            self.assertIsNone(attach_target)

    def test_omx_new_session_wait_rejects_preexisting_pane_without_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"omx-feature-a-1-main-old|||ENVCTL_TMUX_PANE|||%17|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                ]
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md")

            with (
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.02),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
            ):
                attach_target = omx_transport._wait_for_omx_attach_target(
                    rt,
                    repo_root=repo,
                    worktree=worktree,
                    previous_session_id="",
                    previous_session_ids=(),
                    previous_tmux_session_names=("omx-feature-a-1-main-old",),
                    attach_via="attach-session",
                )

            self.assertIsNone(attach_target)

    def test_omx_unavailable_event_includes_state_root_diagnostics(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={"ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true"},
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")

            with (
                redirect_stdout(StringIO()),
                patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_TIMEOUT_SECONDS", 0.02),
                patch("envctl_engine.planning.plan_agent.omx_transport._OMX_SESSION_READY_POLL_INTERVAL_SECONDS", 0.001),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                    created_worktrees=(worktree,),
                )

            self.assertEqual(result.status, "failed")
            failed_events = self._events(rt, "planning.agent_launch.failed")
            unavailable_events = [event for event in failed_events if event.get("reason") == "omx_session_unavailable"]
            self.assertEqual(len(unavailable_events), 1)
            event = unavailable_events[0]
            self.assertEqual(event.get("omx_root"), str(self._expected_omx_root(worktree)))
            self.assertEqual(event.get("session_state_exists"), False)
            self.assertEqual(event.get("session_id_present"), False)
            self.assertIn("tmux_candidates_checked", event)
            self.assertIn("worktree_panes_found", event)

    def test_omx_team_spawn_forces_worker_bypass_args(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="omx",
                cli="codex",
                cli_command="codex --model gpt-5.4 --dangerously-bypass-approvals-and-sandbox",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
                omx_workflow="team",
            )
            popen_calls: list[dict[str, object]] = []

            class _DummyPopen:
                def __init__(self, cmd, **kwargs):  # noqa: ANN001
                    popen_calls.append({"cmd": list(cmd), **kwargs})
                    session_path = Path(str(kwargs["cwd"])) / ".omx" / "state" / "session.json"
                    session_path.parent.mkdir(parents=True, exist_ok=True)
                    session_path.write_text('{"session_id":"omx-abc123"}\n', encoding="utf-8")

                def poll(self):
                    return 0

            with patch("envctl_engine.planning.plan_agent.omx_transport.subprocess.Popen", _DummyPopen):
                error = omx_transport._spawn_omx_session_for_worktree(
                    rt,
                    launch_config=launch_config,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            self.assertEqual(popen_calls[0]["cmd"], ["script", "-qfc", "omx --tmux --madmax", "/dev/null"])
            self.assertEqual(
                cast(dict[str, str], popen_calls[0]["env"])["OMX_TEAM_WORKER_LAUNCH_ARGS"],
                "--dangerously-bypass-approvals-and-sandbox",
            )

    def test_omx_spawn_keeps_pseudo_terminal_input_alive_until_attach_target_is_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="omx",
                cli="codex",
                cli_command="codex --dangerously-bypass-approvals-and-sandbox",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
                omx_workflow="",
            )
            popen_instances: list[object] = []
            popen_calls: list[dict[str, object]] = []

            class _Pipe:
                def __init__(self) -> None:
                    self.closed = False

                def close(self) -> None:
                    self.closed = True

            class _RunningPopen:
                def __init__(self, cmd, **kwargs):  # noqa: ANN001
                    popen_calls.append({"cmd": list(cmd), **kwargs})
                    self.stdin = _Pipe()
                    self.stdout = _Pipe()
                    self.stderr = _Pipe()
                    popen_instances.append(self)

                def poll(self):
                    return None

            with patch("envctl_engine.planning.plan_agent.omx_transport.subprocess.Popen", _RunningPopen):
                error = omx_transport._spawn_omx_session_for_worktree(
                    rt,
                    launch_config=launch_config,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            self.assertEqual(popen_calls[0]["stdin"], subprocess.PIPE)
            self.assertEqual(cast(dict[str, str], popen_calls[0]["env"])["OMX_LAUNCH_POLICY"], "detached-tmux")
            process = cast(Any, popen_instances[0])
            self.assertFalse(process.stdin.closed)
            self.assertTrue(process.stdout.closed)
            self.assertTrue(process.stderr.closed)
            self.assertEqual(cast(Any, rt)._omx_spawn_processes[0].process, process)

    def test_omx_spawn_preserves_codex_config_discovery_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            codex_home = home / ".codex"
            repo.mkdir(parents=True, exist_ok=True)
            codex_home.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_PLAN_AGENT_TERMINALS_ENABLE": "true",
                    "TMUX": "/tmp/tmux-0/default,1,0",
                    "TMUX_PANE": "%7",
                    "ENVCTL_ONLY": "yes",
                },
            )
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md")
            launch_config = launch_support.PlanAgentLaunchConfig(
                enabled=True,
                transport="omx",
                cli="codex",
                cli_command="codex --dangerously-bypass-approvals-and-sandbox",
                preset="implement_task",
                codex_cycles=0,
                codex_cycles_warning=None,
                shell="zsh",
                require_cmux_context=True,
                cmux_workspace="",
                direct_prompt_enabled=False,
                ulw_loop_prefix=False,
                ulw_suffix=False,
                omx_workflow="ralph",
            )
            popen_calls: list[dict[str, object]] = []

            class _DummyPopen:
                def __init__(self, cmd, **kwargs):  # noqa: ANN001
                    popen_calls.append({"cmd": list(cmd), **kwargs})
                    session_path = Path(str(kwargs["cwd"])) / ".omx" / "state" / "session.json"
                    session_path.parent.mkdir(parents=True, exist_ok=True)
                    session_path.write_text('{"session_id":"omx-abc123"}\n', encoding="utf-8")

                def poll(self):
                    return 0

            with (
                patch.dict(os.environ, {"HOME": str(home)}, clear=True),
                patch("envctl_engine.planning.plan_agent.omx_transport.subprocess.Popen", _DummyPopen),
            ):
                error = omx_transport._spawn_omx_session_for_worktree(
                    rt,
                    launch_config=launch_config,
                    worktree=worktree,
                )

            self.assertIsNone(error)
            env = cast(dict[str, str], popen_calls[0]["env"])
            self.assertEqual(env["HOME"], str(home))
            self.assertEqual(env["CODEX_HOME"], str(codex_home))
            self.assertEqual(env["ENVCTL_ONLY"], "yes")
            self.assertNotIn("TMUX", env)
            self.assertNotIn("TMUX_PANE", env)

    def test_find_existing_omx_attach_target_records_active_pane_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            session_path = worktree_root / ".omx" / "state"
            session_path.mkdir(parents=True, exist_ok=True)
            (session_path / "session.json").write_text('{"session_id":"omx-abc123"}\n', encoding="utf-8")
            rt = self._runtime(repo, runtime)
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="%42\n", stderr=""),
                ]
            )

            attach_target = omx_transport._find_existing_omx_attach_target(
                rt,
                repo_root=repo,
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),),
            )

            self.assertIsNotNone(attach_target)
            assert attach_target is not None
            self.assertEqual(attach_target.session_name, omx_transport._omx_tmux_session_name(worktree_root, "omx-abc123"))
            self.assertEqual(attach_target.window_name, "%42")

    def test_tmux_target_accepts_pane_id_directly(self) -> None:
        self.assertEqual(tmux_transport._tmux_target("omx-feature-session", "%42"), "%42")

    def test_cleanup_stale_omx_tmux_locks_ignores_fresh_lock_and_removes_old_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            worktree_root = Path(tmpdir) / "worktree"
            lock_root = worktree_root / ".omx" / "state" / "tmux-extended-keys"
            fresh_lock = lock_root / "fresh.lock"
            stale_lock = lock_root / "stale.lock"
            fresh_lock.mkdir(parents=True, exist_ok=True)
            stale_lock.mkdir(parents=True, exist_ok=True)

            now = time.time()
            stale_time = now - (omx_transport._OMX_TMUX_LOCK_STALE_SECONDS + 10.0)
            fresh_time = now - 1.0
            os.utime(stale_lock, (stale_time, stale_time))
            os.utime(fresh_lock, (fresh_time, fresh_time))

            runtime = self._runtime(Path(tmpdir) / "repo", Path(tmpdir) / "runtime")

            omx_transport._cleanup_stale_omx_tmux_locks(runtime, worktree_root=worktree_root)

            self.assertFalse(stale_lock.exists())
            self.assertTrue(fresh_lock.exists())
            self.assertEqual(
                self._events(runtime, "planning.agent_launch.omx_lock_cleanup"),
                [
                    {
                        "event": "planning.agent_launch.omx_lock_cleanup",
                        "worktree": str(worktree_root.resolve()),
                        "transport": "omx",
                    }
                ],
            )

    def test_omx_launch_reports_spawn_failure(self) -> None:
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

            buffer = StringIO()
            with (
                redirect_stdout(buffer),
                patch("envctl_engine.planning.plan_agent.omx_transport._find_existing_omx_attach_target", return_value=None),
                patch("envctl_engine.planning.plan_agent.omx_transport._spawn_omx_session_for_worktree", return_value="omx exited before creating a managed session"),
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--omx", "--codex"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

            self.assertEqual(result.status, "failed")
            self.assertEqual(result.reason, "launch_failed")
            self.assertEqual(len(result.outcomes), 1)
            self.assertEqual(result.outcomes[0].reason, "omx exited before creating a managed session")
            self.assertIn("omx exited before creating a managed session", buffer.getvalue())

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
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout='  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo /status\n',
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
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach", "-t", expected_session))
            self.assertEqual(rt.process_runner.calls[0], ["tmux", "has-session", "-t", expected_session])
            self.assertEqual(rt.process_runner.calls[1], ["tmux", "list-windows", "-t", expected_session, "-F", "#{window_name}|||ENVCTL_TMUX_PATH|||#{pane_current_path}"])

    def test_tmux_existing_opencode_session_requires_ready_pane(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            expected_session = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),
                cli="opencode",
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout=f"{expected_session}\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"feature-a-1|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout='  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo /status\n',
                        stderr="",
                    ),
                ]
            )

            with patch(
                "envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen",
                return_value="$ cd repo\n$ opencode\nzsh: command not found: opencode\n$ ",
            ):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "failed")
        self.assertIn("existing_opencode_session_unhealthy", result.reason)
        self.assertEqual(len(result.outcomes), 1)
        self.assertIn("zsh: command not found: opencode", str(result.outcomes[0].reason))
        self.assertIsNone(result.attach_target)

    def test_tmux_existing_opencode_session_accepts_active_agent_screen(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-a" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            rt._command_exists = lambda command: command in {"tmux", "opencode", "zsh"}  # type: ignore[assignment]
            expected_session = _tmux_session_name_for_worktree(
                repo,
                CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),
                cli="opencode",
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout=f"{expected_session}\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout=f"feature-a-1|||ENVCTL_TMUX_PATH|||{worktree_root}\n",
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="Sisyphus is working...\nEsc to interrupt\n", stderr=""),
                ]
            )

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree_root, plan_file="a.md"),),
            )

        self.assertEqual(result.status, "failed")
        self.assertIsNotNone(result.attach_target)

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
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout='  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo /status\n',
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
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach", "-t", expected_session))
            self.assertEqual(len(rt.process_runner.calls), 3)

    def test_existing_tmux_session_prompt_explains_no_creates_new_session(self) -> None:
        prompt_target = launch_support.PlanAgentAttachTarget(
            repo_root=Path("/tmp/repo"),
            session_name="envctl-existing",
            window_name="feature-a-1",
            attach_via="attach-session",
            attach_command=("tmux", "attach", "-t", "envctl-existing"),
        )
        captured: list[str] = []
        runtime = self._runtime(Path("/tmp/repo"), Path("/tmp/runtime"))

        def fake_read(prompt: str) -> str:
            captured.append(prompt)
            return "n"

        runtime._read_interactive_command_line = fake_read  # type: ignore[assignment]

        action = tmux_session._prompt_existing_tmux_session_action(runtime, attach_target=prompt_target)

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
                attach_command=("tmux", "attach", "-t", base_session),
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
                patch("envctl_engine.planning.plan_agent.tmux_transport._find_existing_tmux_attach_target", return_value=existing_attach_target),
                patch("envctl_engine.planning.plan_agent.tmux_transport._next_available_tmux_session_name", return_value=new_session) as next_session_mock,
                patch("envctl_engine.planning.plan_agent.tmux_transport._launch_single_tmux_worktree", side_effect=launch_single),
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
            self.assertEqual(result.attach_target.attach_command, ("tmux", "attach", "-t", new_session))

    def test_new_session_command_preserves_ulw_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="feature-a.md")
            command = recovery._new_session_command_for_route(
                rt,
                route=parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--ulw", "--headless"], env={}),
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
                    ulw_loop_prefix=True,
                    ulw_suffix=False,
                ),
                created_worktrees=(worktree,),
            )

        self.assertEqual(
            command,
            (
                "ENVCTL_USE_REPO_WRAPPER=1",
                str(repo.resolve() / "bin" / "envctl"),
                "--plan",
                "feature-a",
                "--tmux",
                "--opencode",
                "--ulw",
                "--tmux-new-session",
                "--headless",
            ),
        )

    def test_new_session_command_preserves_omx_workflow_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime)
            worktree = CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="feature-a.md")
            for token, workflow_name in (("--ultragoal", "ultragoal"), ("--ralph", "ralph"), ("--team", "team")):
                with self.subTest(token=token):
                    command = recovery._new_session_command_for_route(
                        rt,
                        route=parse_route(["--plan", "feature-a", "--omx", token, "--headless"], env={}),
                        launch_config=launch_support.PlanAgentLaunchConfig(
                            enabled=True,
                            transport="omx",
                            cli="codex",
                            cli_command="codex --dangerously-bypass-approvals-and-sandbox",
                            preset="implement_task",
                            codex_cycles=0,
                            codex_cycles_warning=None,
                            shell="zsh",
                            require_cmux_context=True,
                            cmux_workspace="",
                            direct_prompt_enabled=False,
                            ulw_loop_prefix=False,
                            ulw_suffix=False,
                            omx_workflow=cast(Any, workflow_name),
                        ),
                        created_worktrees=(worktree,),
                    )

                    self.assertIn(token, command)
                    self.assertLess(command.index(token), command.index("--tmux-new-session"))

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
                    subprocess.CompletedProcess(
                        args=["tmux"],
                        returncode=0,
                        stdout='  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo /status\n',
                        stderr="",
                    ),
                ]
            )

            attach_target = tmux_transport._find_existing_tmux_attach_target(
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
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="other\n", stderr=""),
                    subprocess.CompletedProcess(args=["tmux"], returncode=0, stdout="feature-a-1\n", stderr=""),
                ]
            )

            with (
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
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
            self.assertIn(["tmux", "set-option", "-t", "envctl-test-session", "mouse", "on"], rt.process_runner.calls)

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
        self.assertIsNotNone(_browser_e2e_instruction_text)
        self.assertIsNotNone(_pr_review_comments_instruction_text)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=0)

        self.assertEqual(workflow.mode, "single_prompt")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [
                ("submit_direct_prompt", "implement_task"),
                ("queue_message", _browser_e2e_instruction_text()),
                ("queue_message", _pr_review_comments_instruction_text()),
            ],
        )

    def test_browser_e2e_followup_requires_main_task_browser_visible_validation_and_fix_loop(self) -> None:
        self.assertIsNotNone(_browser_e2e_instruction_text)
        prompt = _browser_e2e_instruction_text()

        self.assertIn("$browser", prompt)
        self.assertIn("envctl endpoints --project <current-worktree-name> --json", prompt)
        self.assertIn("envctl qa-user ensure --project <current-worktree-name>", prompt)
        self.assertIn("envctl playwright --project <current-worktree-name> -- <command>", prompt)
        self.assertIn("MAIN_TASK.md", prompt)
        self.assertIn("completely implemented end-to-end", prompt)
        self.assertIn("visible in the browser", prompt)
        self.assertIn("fix any issue", prompt)
        self.assertIn("introduced by the implementation", prompt)

    def test_plan_agent_followup_prompts_are_loaded_from_markdown_templates(self) -> None:
        self.assertIsNotNone(_finalization_instruction_text)
        self.assertIsNotNone(_first_cycle_completion_instruction_text)
        self.assertIsNotNone(_intermediate_cycle_completion_instruction_text)
        self.assertIsNotNone(_browser_e2e_instruction_text)
        self.assertIsNotNone(_pr_review_comments_instruction_text)

        template_root = resources.files("envctl_engine.runtime.prompt_templates")

        def assert_prompt_matches_template(prompt_text: Any, template_name: str) -> None:
            self.assertEqual(
                prompt_text(),
                template_root.joinpath(template_name).read_text(encoding="utf-8").strip(),
            )

        assert_prompt_matches_template(_finalization_instruction_text, "_plan_agent_finalization_instruction.md")
        assert_prompt_matches_template(_first_cycle_completion_instruction_text, "_plan_agent_first_cycle_completion.md")
        assert_prompt_matches_template(
            _intermediate_cycle_completion_instruction_text,
            "_plan_agent_intermediate_cycle_completion.md",
        )
        assert_prompt_matches_template(_browser_e2e_instruction_text, "_plan_agent_browser_e2e_followup.md")
        assert_prompt_matches_template(
            _pr_review_comments_instruction_text,
            "_plan_agent_pr_review_comments_followup.md",
        )

    def test_build_plan_agent_workflow_uses_direct_submission_for_ship_release(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(cli="codex", preset="ship_release", codex_cycles=0)

        self.assertEqual(workflow.mode, "single_prompt")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [
                ("submit_direct_prompt", "ship_release"),
                ("queue_message", _browser_e2e_instruction_text()),
                ("queue_message", _pr_review_comments_instruction_text()),
            ],
        )

    def test_build_plan_agent_workflow_for_single_cycle_adds_finalization_and_browser_e2e_messages(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        self.assertIsNotNone(_finalization_instruction_text)
        self.assertIsNotNone(_browser_e2e_instruction_text)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=1)

        self.assertEqual(workflow.mode, "codex_cycles")
        self.assertEqual(
            [(step.kind, step.text) for step in workflow.steps],
            [
                ("submit_direct_prompt", "implement_task"),
                ("queue_direct_prompt", "finalize_task"),
                ("queue_message", _browser_e2e_instruction_text()),
                ("queue_message", _pr_review_comments_instruction_text()),
            ],
        )

    def test_build_plan_agent_workflow_for_multiple_cycles_queues_continue_and_implement_rounds(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        self.assertIsNotNone(_finalization_instruction_text)
        self.assertIsNotNone(_first_cycle_completion_instruction_text)
        self.assertIsNotNone(_browser_e2e_instruction_text)
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
                ("queue_message", _browser_e2e_instruction_text()),
                ("queue_message", _pr_review_comments_instruction_text()),
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
                ("queue_message", _browser_e2e_instruction_text()),
                ("queue_message", _pr_review_comments_instruction_text()),
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
            step = workflow._PlanAgentWorkflowStep(kind="submit_direct_prompt", text="ship_release")

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
            prompt_text, error = workflow._resolve_preset_submission_text(
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

            prompt_text, error = workflow._resolve_preset_submission_text(
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

        prompt_text, error = workflow._resolve_preset_submission_text(
            runtime,
            launch_config=launch_config,
            cli="opencode",
            preset="implement_task",
        )

        self.assertIsNone(error)
        self.assertEqual(prompt_text, "/implement_task")

    def test_implement_task_direct_prompt_injects_current_runtime_addresses(self) -> None:
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )
        runtime.state_repository = _StateRepositoryHarness(
            RunState(
                run_id="run-1",
                mode="trees",
                services={
                    "feature-a Backend": ServiceRecord(
                        name="feature-a Backend",
                        type="backend",
                        cwd="/tmp/repo/backend",
                        actual_port=8201,
                        requested_port=8200,
                        status="running",
                    ),
                    "feature-a Frontend": ServiceRecord(
                        name="feature-a Frontend",
                        type="frontend",
                        cwd="/tmp/repo/frontend",
                        actual_port=9201,
                        status="running",
                    ),
                },
                requirements={
                    "feature-a": RequirementsResult(
                        project="feature-a",
                        components={
                            "postgres": {"enabled": True, "success": True, "final": 5473},
                            "redis": {"enabled": True, "success": True, "final": 6420},
                            "n8n": {"enabled": True, "success": True, "final": 5780},
                            "supabase": {"enabled": False, "success": True, "final": 5633},
                        },
                    )
                },
            )
        )

        prompt_text, error = workflow._resolve_preset_submission_text(
            runtime,
            launch_config=_launch_config_for_tests(cli="codex"),
            cli="codex",
            preset="implement_task",
        )

        self.assertIsNone(error)
        self.assertIn("## Current envctl runtime addresses", prompt_text)
        self.assertIn("Postgres (feature-a): localhost:5473", prompt_text)
        self.assertIn("Redis (feature-a): redis://localhost:6420", prompt_text)
        self.assertIn("n8n (feature-a): http://localhost:5780", prompt_text)
        self.assertIn("Backend (feature-a Backend): http://localhost:8201", prompt_text)
        self.assertIn("Frontend (feature-a Frontend): http://localhost:9201", prompt_text)
        self.assertNotIn("Supabase (feature-a): http://localhost:5633", prompt_text)

    def test_worktree_prompt_does_not_inject_runtime_addresses_from_other_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            target_root = repo / "trees" / "feature-b" / "1"
            target_root.mkdir(parents=True, exist_ok=True)
            runtime = _RuntimeHarness(
                config=load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_dir)}),
                env={},
                process_runner=_RecordingRunner(),
            )
            runtime.state_repository = _StateRepositoryHarness(
                RunState(
                    run_id="run-previous",
                    mode="trees",
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(repo / "trees" / "feature-a" / "1" / "backend"),
                            actual_port=8201,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-a-1": RequirementsResult(
                            project="feature-a-1",
                            components={"redis": {"enabled": True, "success": True, "final": 6420}},
                        )
                    },
                )
            )

            prompt_text, error = _workflow_step_prompt_text(
                runtime,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
                step=workflow._PlanAgentWorkflowStep(kind="submit_direct_prompt", text="implement_task"),
                worktree=CreatedPlanWorktree(name="feature-b-1", root=target_root, plan_file="features/feature-b.md"),
            )

        self.assertIsNone(error)
        self.assertNotIn("## Current envctl runtime addresses", prompt_text)
        self.assertNotIn("feature-a", prompt_text)
        self.assertNotIn("localhost:8201", prompt_text)
        self.assertNotIn("redis://localhost:6420", prompt_text)

    def test_browser_e2e_followup_injects_original_plan_and_runtime_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            original_plan = repo / "todo" / "plans" / "implementations" / "feature-a.md"
            worktree_root = repo / "trees" / "feature-a" / "1"
            original_plan.parent.mkdir(parents=True, exist_ok=True)
            worktree_root.mkdir(parents=True, exist_ok=True)
            original_plan.write_text("# Original task\n", encoding="utf-8")
            runtime = _RuntimeHarness(
                config=load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_dir)}),
                env={},
                process_runner=_RecordingRunner(),
            )
            runtime.state_repository = _StateRepositoryHarness(
                RunState(
                    run_id="run-1",
                    mode="trees",
                    services={
                        "feature-a Frontend": ServiceRecord(
                            name="feature-a Frontend",
                            type="frontend",
                            cwd=str(worktree_root / "frontend"),
                            actual_port=9300,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-a": RequirementsResult(
                            project="feature-a",
                            components={"postgres": {"enabled": True, "success": True, "final": 5500}},
                        )
                    },
                )
            )

            prompt_text, error = _workflow_step_prompt_text(
                runtime,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
                step=workflow._PlanAgentWorkflowStep(
                    kind="queue_message",
                    text=_browser_e2e_instruction_text(),
                ),
                worktree=CreatedPlanWorktree(
                    name="feature-a-1",
                    root=worktree_root,
                    plan_file="implementations/feature-a.md",
                ),
            )

        self.assertIsNone(error)
        self.assertIn("## Original task source for E2E validation", prompt_text)
        self.assertIn(str(original_plan), prompt_text)
        self.assertIn("Use this original plan file before the current MAIN_TASK.md", prompt_text)
        self.assertIn("## Current envctl runtime addresses", prompt_text)
        self.assertIn("Postgres (feature-a): localhost:5500", prompt_text)
        self.assertIn("Frontend (feature-a Frontend): http://localhost:9300", prompt_text)

    def test_browser_e2e_followup_omits_stale_runtime_addresses_for_other_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-b" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            runtime = _RuntimeHarness(
                config=load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_dir)}),
                env={},
                process_runner=_RecordingRunner(),
            )
            runtime.state_repository = _StateRepositoryHarness(
                RunState(
                    run_id="run-previous",
                    mode="trees",
                    services={
                        "feature-a-1 Frontend": ServiceRecord(
                            name="feature-a-1 Frontend",
                            type="frontend",
                            cwd=str(repo / "trees" / "feature-a" / "1" / "frontend"),
                            actual_port=9300,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-a-1": RequirementsResult(
                            project="feature-a-1",
                            components={"n8n": {"enabled": True, "success": True, "final": 5780}},
                        )
                    },
                )
            )

            prompt_text, error = _workflow_step_prompt_text(
                runtime,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
                step=workflow._PlanAgentWorkflowStep(
                    kind="queue_message",
                    text=_browser_e2e_instruction_text(),
                ),
                worktree=CreatedPlanWorktree(
                    name="feature-b-1",
                    root=worktree_root,
                    plan_file="features/feature-b.md",
                ),
            )

        self.assertIsNone(error)
        self.assertIn("## Original task source for E2E validation", prompt_text)
        self.assertNotIn("## Current envctl runtime addresses", prompt_text)
        self.assertNotIn("feature-a", prompt_text)
        self.assertNotIn("localhost:9300", prompt_text)
        self.assertNotIn("http://localhost:5780", prompt_text)

    def test_browser_e2e_followup_injects_matching_worktree_runtime_addresses(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime_dir = Path(tmpdir) / "runtime"
            worktree_root = repo / "trees" / "feature-b" / "1"
            worktree_root.mkdir(parents=True, exist_ok=True)
            runtime = _RuntimeHarness(
                config=load_config({"RUN_REPO_ROOT": str(repo), "RUN_SH_RUNTIME_DIR": str(runtime_dir)}),
                env={},
                process_runner=_RecordingRunner(),
            )
            runtime.state_repository = _StateRepositoryHarness(
                RunState(
                    run_id="run-current",
                    mode="trees",
                    services={
                        "feature-b-1 Backend": ServiceRecord(
                            name="feature-b-1 Backend",
                            type="backend",
                            cwd=str(worktree_root / "backend"),
                            actual_port=8300,
                            status="running",
                        )
                    },
                    requirements={
                        "feature-b-1": RequirementsResult(
                            project="feature-b-1",
                            components={"redis": {"enabled": True, "success": True, "final": 6421}},
                        )
                    },
                )
            )

            prompt_text, error = _workflow_step_prompt_text(
                runtime,
                launch_config=_launch_config_for_tests(cli="codex"),
                cli="codex",
                step=workflow._PlanAgentWorkflowStep(
                    kind="queue_message",
                    text=_browser_e2e_instruction_text(),
                ),
                worktree=CreatedPlanWorktree(
                    name="feature-b-1",
                    root=worktree_root,
                    plan_file="features/feature-b.md",
                ),
            )

        self.assertIsNone(error)
        self.assertIn("## Current envctl runtime addresses", prompt_text)
        self.assertIn("Redis (feature-b-1): redis://localhost:6421", prompt_text)
        self.assertIn("Backend (feature-b-1 Backend): http://localhost:8300", prompt_text)


    def test_runtime_addresses_are_not_injected_for_other_direct_presets(self) -> None:
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )
        runtime.state_repository = _StateRepositoryHarness(
            RunState(
                run_id="run-1",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd="/tmp/repo/backend",
                        actual_port=8000,
                    )
                },
                requirements={},
            )
        )

        prompt_text, error = workflow._resolve_preset_submission_text(
            runtime,
            launch_config=_launch_config_for_tests(cli="codex"),
            cli="codex",
            preset="ship_release",
        )

        self.assertIsNone(error)
        self.assertNotIn("Current envctl runtime addresses", prompt_text)
        self.assertNotIn("localhost:8000", prompt_text)

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

            prompt_text, error = workflow._resolve_preset_submission_text(
                runtime,
                launch_config=launch_config,
                cli="opencode",
                preset="implement_task",
            )

        self.assertIsNone(error)
        self.assertTrue(prompt_text.startswith("/ulw-loop "))
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

        prompt_text, error = workflow._resolve_preset_submission_text(
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

        prompt_text, error = workflow._resolve_preset_submission_text(
            runtime,
            launch_config=launch_config,
            cli="opencode",
            preset="implement_task",
        )

        self.assertEqual(prompt_text, "")
        self.assertEqual(error, "prompt_resolution_failed: ulw_loop_prefix_requires_direct_prompt")

    def test_shape_prompt_text_rejects_multiple_slash_commands_for_direct_prompts(self) -> None:
        shaped, error = workflow._shape_prompt_text(
            "/implement_task",
            direct_prompt=True,
            ulw_loop_prefix=True,
            ulw_suffix=False,
        )

        self.assertEqual(shaped, "")
        self.assertEqual(error, "prompt_resolution_failed: multiple_slash_commands_not_allowed")

    def test_shape_prompt_text_rejects_embedded_second_slash_command_for_direct_prompts(self) -> None:
        shaped, error = workflow._shape_prompt_text(
            "Implement this directly.\n/implement_task",
            direct_prompt=True,
            ulw_loop_prefix=True,
            ulw_suffix=False,
        )

        self.assertEqual(shaped, "")
        self.assertEqual(error, "prompt_resolution_failed: multiple_slash_commands_not_allowed")

    def test_shape_prompt_text_preserves_existing_ulw_loop_prefix_and_allows_suffix(self) -> None:
        shaped, error = workflow._shape_prompt_text(
            "/ulw-loop Implement this directly.",
            direct_prompt=True,
            ulw_loop_prefix=True,
            ulw_suffix=True,
        )

        self.assertIsNone(error)
        self.assertEqual(shaped, "/ulw-loop Implement this directly. ulw")

    def test_shape_prompt_text_allows_absolute_path_literals_in_direct_prompts(self) -> None:
        shaped, error = workflow._shape_prompt_text(
            'Review bundle: "/tmp/review.md"\nWorktree directory: "/tmp/tree"',
            direct_prompt=True,
            ulw_loop_prefix=True,
            ulw_suffix=False,
        )

        self.assertIsNone(error)
        self.assertTrue(shaped.startswith("/ulw-loop "))
        self.assertIn('Review bundle: "/tmp/review.md"', shaped)

    def test_build_plan_agent_workflow_bounds_large_cycle_counts(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=999)

        self.assertEqual(workflow.mode, "codex_cycles")
        self.assertEqual(workflow.codex_cycles, 10)
        self.assertEqual(len(workflow.steps), 3 + (1 + 3 * (workflow.codex_cycles - 1)))

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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter()),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._queue_codex_message", return_value=True),
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
                        "queued_steps": 6,
                        "queued_steps_confirmed": 6,
                        "transport": "cmux",
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
                "envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen",
                side_effect=lambda *_args, **_kwargs: next(screens, ready_screen),
            ),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            ready = _wait_for_codex_queue_ready(runtime, workspace_id="workspace:7", surface_id="surface:9")

        self.assertTrue(ready)

    def test_codex_cycle_queue_types_message_before_waiting_for_tab_ready(self) -> None:
        self.assertIsNotNone(_build_plan_agent_workflow)
        workflow = _build_plan_agent_workflow(cli="codex", preset="implement_task", codex_cycles=1)
        queued_steps = workflow.steps[1:2]
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
            patch("envctl_engine.planning.plan_agent.cmux_transport._paste_surface_text", side_effect=fake_paste_text),
            patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", side_effect=fake_send_key),
            patch(
                "envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen",
                side_effect=lambda *_args, **_kwargs: typed_screen if state["typed"] else busy_screen,
            ),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            reason = cmux_transport._queue_codex_workflow_steps(
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
            patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen", side_effect=fake_read_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = cmux_transport._queue_codex_message(
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
            patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen", return_value=queue_hint_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = cmux_transport._queue_codex_message(
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
            patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen", side_effect=fake_read_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = cmux_transport._queue_codex_message(
                runtime,
                workspace_id="workspace:7",
                surface_id="surface:9",
                text=queued_text,
                require_text_match=False,
            )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])

    def test_cmux_codex_queue_fails_when_message_remains_in_textbox_after_tab(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body"
        stuck_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "  Direct queued prompt body\n"
            "  tab to queue message\n"
        )
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            return None

        with (
            patch("envctl_engine.planning.plan_agent.cmux_transport._send_surface_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.cmux_transport._read_surface_screen", return_value=stuck_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = cmux_transport._queue_codex_message(
                runtime, workspace_id="workspace:7", surface_id="surface:9", text=queued_text, require_text_match=False
            )

        self.assertFalse(queued)
        self.assertEqual(sent_keys, ["tab", "tab"])

    def test_tmux_codex_queue_confirms_message_after_tab(self) -> None:
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
        committed_screen = "• Queued follow-up messages\n"
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            if key == "tab":
                state["stage"] = "committed"
            return None

        def fake_read_screen(*_args, **_kwargs):  # noqa: ANN202, ANN001
            return queue_hint_screen if state["stage"] == "typed" else committed_screen

        with (
            patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen", side_effect=fake_read_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = tmux_transport._queue_tmux_codex_message(
                runtime, session_name="envctl-test", window_name="feature-a-1", text=queued_text, require_text_match=False
            )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])

    def test_tmux_codex_queue_fails_when_message_remains_in_textbox_after_tab(self) -> None:
        sent_keys: list[str] = []
        queued_text = "Direct queued prompt body"
        stuck_screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "  Direct queued prompt body\n"
            "  tab to queue message\n"
        )
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            return None

        with (
            patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_key", side_effect=fake_send_key),
            patch("envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen", return_value=stuck_screen),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = tmux_transport._queue_tmux_codex_message(
                runtime, session_name="envctl-test", window_name="feature-a-1", text=queued_text, require_text_match=False
            )

        self.assertFalse(queued)
        self.assertEqual(sent_keys, ["tab", "tab"])

    def test_tmux_codex_queue_accepts_pasted_content_only_after_post_tab_confirmation(self) -> None:
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
        committed_screen = "• Queued follow-up messages\n"
        runtime = _RuntimeHarness(
            config=load_config({"RUN_REPO_ROOT": "/tmp/repo", "RUN_SH_RUNTIME_DIR": "/tmp/runtime"}),
            env={},
            process_runner=_RecordingRunner(),
        )

        def fake_send_key(*_args, key, **_kwargs):  # noqa: ANN202, ANN001
            sent_keys.append(key)
            if key == "tab":
                state["stage"] = "committed"
            return None

        with (
            patch("envctl_engine.planning.plan_agent.tmux_transport._send_tmux_key", side_effect=fake_send_key),
            patch(
                "envctl_engine.planning.plan_agent.tmux_transport._read_tmux_screen",
                side_effect=lambda *_args, **_kwargs: queue_hint_screen if state["stage"] == "typed" else committed_screen,
            ),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter(step=0.1)),
            patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
        ):
            queued = tmux_transport._queue_tmux_codex_message(
                runtime, session_name="envctl-test", window_name="feature-a-1", text=queued_text, require_text_match=False
            )

        self.assertTrue(queued)
        self.assertEqual(sent_keys, ["tab"])

    def test_review_prompt_arguments_preserve_newlines_for_direct_codex_submission(self) -> None:
        rendered = workflow._review_prompt_arguments(
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
                    "ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE": "false",
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter()),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_codex_queue_ready", return_value=True),
                patch(
                    "envctl_engine.planning.plan_agent.cmux_transport._paste_surface_text",
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
                        "queue_failed_step_index": 0,
                        "queue_failed_step_kind": "queue_direct_prompt",
                        "transport": "cmux",
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
                        "queue_failed_step_index": 0,
                        "queue_failed_step_kind": "queue_direct_prompt",
                        "transport": "cmux",
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
                    "envctl_engine.planning.plan_agent.launch._ensure_workspace_id",
                    return_value=_WorkspaceLaunchTarget(workspace_id="workspace:7", created=False),
                ),
                patch(
                    "envctl_engine.planning.plan_agent.launch._launch_single_worktree",
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
                    "codex_goal_enable": True,
                    "browser_e2e_followup_enable": True,
                    "pr_review_comments_followup_enable": True,
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None) as sleep_mock,
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.monotonic", new=_monotonic_counter()),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
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
            self.assertIn(0.15, [call.args[0] for call in sleep_mock.call_args_list])
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_picker_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_submit_ready", return_value=None),
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
        self.assertTrue(terminal_screen._screen_looks_ready("opencode", screen))

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

    def test_ai_cli_ready_window_allows_slower_opencode_startup(self) -> None:
        self.assertEqual(config._cli_ready_delay_seconds("codex"), 5.0)
        self.assertEqual(config._cli_ready_delay_seconds("opencode"), 15.0)

    def test_workspace_entries_are_parsed_from_list_output(self) -> None:
        payload = """
        * workspace:1  envctl  [selected]
          workspace:2  envctl implementation
          workspace:3  supportopia
        """
        self.assertEqual(
            cmux_transport._workspace_entries_from_list_output(payload),
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
            cmux_transport._surface_ids_from_list_output(payload),
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
            cmux_transport._surface_ids_from_list_output(payload),
            ("surface:20",),
        )

    def test_surface_ids_parser_ignores_non_numeric_surface_tokens(self) -> None:
        payload = """
        pane:1
          surface:notes [terminal] "~/repo"
          surface:21 [terminal] "feature-a-1" [selected]
        """
        self.assertEqual(
            cmux_transport._surface_ids_from_list_output(payload),
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
        self.assertEqual(cmux_transport._workspace_ref_from_identify_output(payload), "workspace:4")

    def test_opencode_ready_screen_rejects_loading_text_even_with_prompt_glyphs(self) -> None:
        screen = "Loading workspace...\n  ›\n"
        self.assertFalse(_screen_looks_ready("opencode", screen))

    def test_opencode_ready_screen_rejects_plain_shell_prompt_glyph(self) -> None:
        screen = "$ cd repo\n❯\n"
        self.assertFalse(_screen_looks_ready("opencode", screen))

    def test_opencode_ready_screen_rejects_stale_ready_scrollback_followed_by_shell_failure(self) -> None:
        screen = (
            '  ┃  Ask anything... "Fix broken tests"\n'
            "  ctrl+p commands\n"
            "  ~/repo /status\n"
            "zsh: command not found: opencode\n"
            "$ "
        )
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

    def test_opencode_post_submit_rejects_unchanged_composer(self) -> None:
        prompt = "/ulw-loop\n\nImplement task"
        unchanged = "  ┃  /ulw-loop\n  ┃\n  ┃  Implement task\n  ctrl+p commands\n  ~/repo /status\n"
        self.assertFalse(terminal_screen._post_submit_screen_looks_accepted("opencode", unchanged, prompt))

    def test_opencode_post_submit_rejects_unknown_screen(self) -> None:
        self.assertFalse(terminal_screen._post_submit_screen_looks_accepted("opencode", "shell prompt\n$ ", "/ulw-loop"))

    def test_opencode_post_submit_accepts_busy_or_cleared_screen(self) -> None:
        prompt = "/ulw-loop\n\nImplement task"
        busy = "Sisyphus is working...\nEsc to interrupt\n"
        cleared = '  ┃  Ask anything... "Follow up"\n  ctrl+p commands\n  ~/repo /status\n'
        self.assertTrue(terminal_screen._post_submit_screen_looks_accepted("opencode", busy, prompt))
        self.assertTrue(terminal_screen._post_submit_screen_looks_accepted("opencode", cleared, prompt))

    def test_opencode_post_submit_accepts_busy_screen_with_prompt_history(self) -> None:
        prompt = "/ulw-loop\n\nImplement task"
        busy_with_history = "  ┃  /ulw-loop\n  ┃\n  ┃  Implement task\nSisyphus is working...\nEsc to interrupt\n"

        self.assertTrue(terminal_screen._post_submit_screen_looks_accepted("opencode", busy_with_history, prompt))

    def test_opencode_active_screen_rejects_generic_shell_output(self) -> None:
        shell_ctrl_c = "Run this command and press Ctrl+C to stop it.\n$ "
        shell_working = "Tests are working as expected.\n$ "

        self.assertFalse(_screen_looks_active("opencode", shell_ctrl_c))
        self.assertFalse(_screen_looks_active("opencode", shell_working))

    def test_opencode_active_screen_requires_opencode_activity_context(self) -> None:
        screen = "Sisyphus is working...\nEsc to interrupt\n"

        self.assertTrue(_screen_looks_active("opencode", screen))

    def test_ai_cli_failure_excerpt_redacts_sensitive_values(self) -> None:
        result = launch_support.AiCliReadyResult(
            ready=False,
            reason="opencode_ready_timeout",
            screen_excerpt=terminal_screen._screen_excerpt(
                "API_KEY=super-secret\n"
                "https://user:password@example.test/path\n"
                "SESSION_TOKEN=abc123\n"
                "Authorization: Bearer bearer-secret\n"
                "export SESSION_TOKEN space-secret\n"
                "API_KEY another-secret\n"
            ),
        )

        rendered = terminal_screen._format_ai_cli_ready_failure(result)

        self.assertIn("<redacted>", rendered)
        self.assertNotIn("super-secret", rendered)
        self.assertNotIn("user:password", rendered)
        self.assertNotIn("abc123", rendered)
        self.assertNotIn("bearer-secret", rendered)
        self.assertNotIn("space-secret", rendered)
        self.assertNotIn("another-secret", rendered)

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

            with patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None):
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

            with patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None):
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
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

            with patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None):
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._start_background_surface_bootstrap", return_value=None),
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_picker_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_submit_ready", return_value=None),
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_cli_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_picker_ready", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_prompt_submit_ready", return_value=None),
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
                patch("envctl_engine.planning.plan_agent.cmux_transport.time.sleep", return_value=None),
                patch("envctl_engine.planning.plan_agent.cmux_transport.threading.Thread", _ImmediateThread),
                patch("envctl_engine.planning.plan_agent.cmux_transport._wait_for_cli_ready", return_value=None),
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
            self.assertTrue(str(direct_prompt_calls[0][-1]).startswith("/ulw-loop Review prompt body"))
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
            original_plan_path = workflow._review_original_plan_path(
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

            original_plan_path = workflow._review_original_plan_path(
                "feature-a-1",
                project_root,
                repo_root=repo,
            )

            self.assertIsNone(original_plan_path)

    def test_review_launch_does_not_infer_when_recorded_plan_file_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            project_root = repo / "trees" / "implementations_task" / "1"
            inferred_plan = repo / "todo" / "done" / "implementations" / "task.md"
            project_root.mkdir(parents=True, exist_ok=True)
            inferred_plan.parent.mkdir(parents=True, exist_ok=True)
            inferred_plan.write_text("# done plan\n", encoding="utf-8")
            (project_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps({"schema_version": 1, "plan_file": "implementations/missing.md"}) + "\n",
                encoding="utf-8",
            )

            original_plan_path = workflow._review_original_plan_path(
                "implementations_task-1",
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

            original_plan_path = workflow._review_original_plan_path(
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

            original_plan_path = workflow._review_original_plan_path(
                "features_task",
                project_root,
                repo_root=repo,
            )

            self.assertEqual(original_plan_path, active_plan.resolve())

    def test_superset_alias_selects_superset_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config_obj = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "SUPERSET": "true",
                    "SUPERSET_PROJECT": "proj-1",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config_obj,
                {},
                route=parse_route(["--plan", "feature-a"], env={}),
            )

        self.assertEqual(launch_config.transport, "superset")
        self.assertTrue(launch_config.enabled)
        self.assertEqual(launch_config.superset_project, "proj-1")

    def test_superset_project_alias_alone_selects_superset_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config_obj = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "SUPERSET_PROJECT": "proj-1",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config_obj,
                {},
                route=parse_route(["--plan", "feature-a"], env={}),
            )

        self.assertEqual(launch_config.transport, "superset")
        self.assertTrue(launch_config.enabled)
        self.assertEqual(launch_config.superset_project, "proj-1")

    def test_canonical_superset_project_alone_selects_superset_transport(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config_obj = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_PLAN_AGENT_SUPERSET_PROJECT": "proj-1",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config_obj,
                {},
                route=parse_route(["--plan", "feature-a"], env={}),
            )

        self.assertEqual(launch_config.transport, "superset")
        self.assertTrue(launch_config.enabled)
        self.assertEqual(launch_config.superset_project, "proj-1")

    def test_canonical_surface_transport_cmux_wins_over_superset_project_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            config_obj = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "SUPERSET_PROJECT": "proj-1",
                    "ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT": "cmux",
                }
            )

            launch_config = launch_support.resolve_plan_agent_launch_config(
                config_obj,
                {},
                route=parse_route(["--plan", "feature-a"], env={}),
            )

        self.assertEqual(launch_config.transport, "cmux")
        self.assertTrue(launch_config.enabled)
        self.assertEqual(launch_config.superset_project, "proj-1")

    def test_superset_launch_missing_project_without_workspace_skips_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"SUPERSET": "true"})

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
            )

        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "missing_superset_project")
        self.assertEqual(rt.process_runner.calls, [])

    def test_superset_project_launch_uses_public_workspace_create_cli_and_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            worktree.mkdir(parents=True, exist_ok=True)
            host_db = self._superset_host_db(home)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "HOME": str(home),
                    "SUPERSET": "true",
                    "SUPERSET_PROJECT": "proj-1",
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES": "2",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/superset\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-123"}}),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout="", stderr=""),
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(
                        CreatedPlanWorktree(
                            name="features_envctl_plan_agent_superset_lean_launch_1",
                            root=worktree,
                            plan_file="a.md",
                        ),
                    ),
                )
            create_call = rt.process_runner.calls[1]
            agent_id = create_call[create_call.index("--agent") + 1]
            with sqlite3.connect(host_db) as connection:
                host_agent_row = connection.execute(
                    "select command, args_json, prompt_transport from host_agent_configs where id = ?",
                    (agent_id,),
                ).fetchone()
            launcher_path = Path(json.loads(host_agent_row[1])[0]) if host_agent_row else Path()
            launcher_exists = launcher_path.exists()
            launcher_source = launcher_path.read_text(encoding="utf-8") if launcher_exists else ""

        rendered = buffer.getvalue()
        self.assertEqual(result.status, "launched")
        self.assertEqual(result.outcomes[0].surface_id, "ws-123")
        self.assertIn("features_envctl_plan_agent_superset_lean_launch_1", rendered)
        self.assertIn("ws-123", rendered)
        self.assertEqual(rt.process_runner.calls[0], ["git", "-C", str(worktree), "branch", "--show-current"])
        self.assertEqual(create_call[:7], ["superset", "workspaces", "create", "--local", "--project", "proj-1", "--name"])
        self.assertIn("--branch", create_call)
        self.assertEqual(create_call[create_call.index("--branch") + 1], "feature/superset")
        self.assertIn("--agent", create_call)
        self.assertRegex(agent_id, r"^[0-9a-f-]{36}$")
        self.assertNotEqual(agent_id, "codex")
        self.assertIn("--prompt", create_call)
        prompt = create_call[create_call.index("--prompt") + 1]
        payload = json.loads(prompt)
        self.assertEqual(payload["version"], 1)
        self.assertTrue(payload["goal"].startswith("Implement the envctl plan-agent task for a.md"))
        self.assertIn("Workflow mode: single_prompt.", payload["goal"])
        self.assertIn("Authoritative source of truth", payload["prompt"])
        self.assertEqual(create_call[-1], "--json")
        self.assertEqual(rt.process_runner.calls[2], ["superset", "workspaces", "open", "ws-123"])
        self.assertIsNotNone(host_agent_row)
        self.assertEqual(host_agent_row[0], "python3")
        self.assertEqual(host_agent_row[2], "argv")
        self.assertEqual(launcher_path, worktree / ".envctl-state" / "superset-codex-goal-launcher.py")
        self.assertTrue(launcher_exists)
        self.assertIn('if b"Goal active" in buffer:', launcher_source)
        self.assertIn('f"/goal {goal}"', launcher_source)
        self.assertIn('os.write(master_fd, b"\\r")', launcher_source)
        self.assertIn('os.write(master_fd, b"\\n")', launcher_source)
        self.assertIn("goal_submit_attempts < 6", launcher_source)
        self.assertIn("prompt_submit_attempts < 6", launcher_source)
        self.assertIn("prompt_pasted = True", launcher_source)
        self.assertNotIn("goal_deadline", launcher_source)
        flattened = "\n".join(" ".join(call) for call in rt.process_runner.calls)
        self.assertNotIn("cmux read-screen", flattened)
        self.assertNotIn("cmux send-key", flattened)
        self.assertNotIn("cmux set-buffer", flattened)
        self.assertNotIn("cmux paste-buffer", flattened)
        warnings = self._events(rt, "planning.agent_launch.superset_cycles_unsupported")
        self.assertEqual(len(warnings), 1)
        goal_events = self._events(rt, "planning.agent_launch.codex_goal_launcher_prepared")
        self.assertEqual(len(goal_events), 1)
        self.assertEqual(goal_events[0]["transport"], "superset")

    def test_superset_project_launch_honors_no_goal_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_PROJECT": "proj-1",
                    "ENVCTL_PLAN_AGENT_SUPERSET_OPEN": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/superset\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-123"}}),
                        stderr="",
                    ),
                ]
            )

            launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a", "--no-goal"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
            )

        create_call = rt.process_runner.calls[1]
        prompt = create_call[create_call.index("--prompt") + 1]
        self.assertFalse(prompt.startswith("/goal "))
        self.assertEqual(self._events(rt, "planning.agent_launch.codex_goal_launcher_prepared"), [])

    def test_superset_workspace_launch_uses_public_agent_run_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_WORKSPACE": "ws-existing",
                    "ENVCTL_PLAN_AGENT_SUPERSET_OPEN": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-existing"}, "session": {"id": "agent-1"}}),
                        stderr="",
                    )
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

        rendered = buffer.getvalue()
        self.assertEqual(result.status, "launched")
        run_call = rt.process_runner.calls[0]
        self.assertEqual(run_call[:5], ["superset", "agents", "run", "--workspace", "ws-existing"])
        self.assertIn("--agent", run_call)
        self.assertIn("--prompt", run_call)
        self.assertEqual(run_call[-1], "--json")
        self.assertEqual(result.outcomes[0].surface_id, "ws-existing")
        self.assertIn("feature-a-1", rendered)
        self.assertIn("ws-existing", rendered)
        self.assertIn("superset workspaces open ws-existing", rendered)

    def test_superset_project_launch_uses_top_level_workspace_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_PROJECT": "proj-1",
                    "ENVCTL_PLAN_AGENT_SUPERSET_OPEN": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/top\n", stderr=""),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout=json.dumps({"id": "ws-top"}), stderr=""),
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "launched")
        self.assertEqual(result.outcomes[0].surface_id, "ws-top")
        self.assertIn("ws-top", buffer.getvalue())
        self.assertIn("superset workspaces open ws-top", buffer.getvalue())

    def test_superset_project_launch_uses_agents_workspace_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"SUPERSET_PROJECT": "proj-1"})
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/agents\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"agents": [{"workspace_id": "ws-agent"}]}),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout="", stderr=""),
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "launched")
        self.assertEqual(result.outcomes[0].surface_id, "ws-agent")
        self.assertEqual(rt.process_runner.calls[2], ["superset", "workspaces", "open", "ws-agent"])

    def test_superset_success_with_non_json_stdout_reports_missing_workspace_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"SUPERSET_PROJECT": "proj-1"})
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/non-json\n", stderr=""),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout="workspace created", stderr=""),
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "launched")
        self.assertIsNone(result.outcomes[0].surface_id)
        self.assertIn("no workspace id was returned", buffer.getvalue())
        self.assertEqual(len(self._events(rt, "planning.agent_launch.superset_debug_output")), 1)

    def test_superset_project_launch_uses_host_instead_of_local(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_PROJECT": "proj-1",
                    "ENVCTL_PLAN_AGENT_SUPERSET_HOST": "https://superset.example",
                    "ENVCTL_PLAN_AGENT_SUPERSET_OPEN": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/host\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-host"}}),
                        stderr="",
                    ),
                ]
            )

            launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
            )

        create_call = rt.process_runner.calls[1]
        self.assertIn("--host", create_call)
        self.assertEqual(create_call[create_call.index("--host") + 1], "https://superset.example")
        self.assertNotIn("--local", create_call)

    def test_superset_project_launch_falls_back_to_worktree_name_when_branch_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_PROJECT": "proj-1",
                    "ENVCTL_PLAN_AGENT_SUPERSET_OPEN": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=1, stdout="", stderr="not a branch"),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-fallback"}}),
                        stderr="",
                    ),
                ]
            )

            launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
            )

        create_call = rt.process_runner.calls[1]
        self.assertEqual(create_call[create_call.index("--branch") + 1], "feature-a-1")
        fallback_events = self._events(rt, "planning.agent_launch.superset_branch_fallback")
        self.assertEqual(len(fallback_events), 1)
        self.assertEqual(fallback_events[0]["fallback"], "feature-a-1")

    def test_superset_open_failure_emits_event_and_keeps_launch_successful(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            worktree.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"SUPERSET_PROJECT": "proj-1"})
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/open\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-open"}}),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["superset"], returncode=1, stdout="", stderr="browser failed"),
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "launched")
        self.assertEqual(result.outcomes[0].status, "launched")
        self.assertIn("browser failed", buffer.getvalue())
        open_failed_events = self._events(rt, "planning.agent_launch.superset_open_failed")
        self.assertEqual(len(open_failed_events), 1)
        self.assertEqual(open_failed_events[0]["reason"], "superset_open_failed")
        self.assertEqual(open_failed_events[0]["workspace_id"], "ws-open")
        self.assertEqual(open_failed_events[0]["error"], "browser failed")

    def test_superset_open_verifies_desktop_workspace_cache_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            db_path = home / ".superset" / "local.db"
            worktree.mkdir(parents=True, exist_ok=True)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(db_path) as connection:
                connection.execute("create table workspaces (id text primary key)")
                connection.execute("insert into workspaces (id) values (?)", ("ws-ready",))
            rt = self._runtime(repo, runtime, env={"SUPERSET_PROJECT": "proj-1", "HOME": str(home)})
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/open\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-ready"}}),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout="", stderr=""),
                ]
            )

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
            )

        self.assertEqual(result.status, "launched")
        self.assertEqual(result.outcomes[0].status, "launched")
        ready_events = self._events(rt, "planning.agent_launch.superset_desktop_workspace_ready")
        self.assertEqual(len(ready_events), 1)
        self.assertEqual(ready_events[0]["workspace_id"], "ws-ready")

    def test_superset_open_bridges_desktop_workspace_cache_from_host_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            superset_dir = home / ".superset"
            local_db = superset_dir / "local.db"
            tanstack_db = superset_dir / "tanstack-db.sqlite"
            host_db = superset_dir / "host" / "host-1" / "host.db"
            worktree.mkdir(parents=True, exist_ok=True)
            local_db.parent.mkdir(parents=True, exist_ok=True)
            host_db.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(local_db) as connection:
                connection.execute(
                    """
                    create table projects (
                        id text primary key,
                        main_repo_path text,
                        name text,
                        color text,
                        tab_order integer,
                        last_opened_at integer,
                        created_at integer,
                        default_branch text,
                        github_owner text,
                        default_app text
                    )
                    """
                )
                connection.execute(
                    """
                    create table worktrees (
                        id text primary key,
                        project_id text,
                        path text,
                        branch text,
                        base_branch text,
                        created_at integer,
                        created_by_superset integer
                    )
                    """
                )
                connection.execute(
                    """
                    create table workspaces (
                        id text primary key,
                        project_id text,
                        worktree_id text,
                        type text,
                        branch text,
                        name text,
                        tab_order integer,
                        created_at integer,
                        updated_at integer,
                        last_opened_at integer,
                        is_unread integer,
                        is_unnamed integer
                    )
                    """
                )
            with sqlite3.connect(tanstack_db) as connection:
                connection.execute(
                    """
                    create table collection_registry (
                        collection_id text primary key,
                        table_name text not null unique,
                        tombstone_table_name text not null unique,
                        schema_version integer not null,
                        updated_at integer not null
                    )
                    """
                )
                connection.execute(
                    """
                    insert into collection_registry
                    (collection_id, table_name, tombstone_table_name, schema_version, updated_at)
                    values ('v2_workspaces-org-1', 'c_workspaces_org_1', 'c_workspaces_org_1_tombstones', 1, 1)
                    """
                )
                connection.execute(
                    "create table c_workspaces_org_1 (key text primary key, value text, metadata text, row_version integer)"
                )
            with sqlite3.connect(host_db) as connection:
                connection.execute(
                    "create table projects (id text primary key, repo_path text, repo_owner text, repo_name text, created_at text)"
                )
                connection.execute(
                    "create table workspaces (id text primary key, worktree_path text, branch text, created_at text)"
                )
                connection.execute(
                    "insert into projects values (?, ?, ?, ?, ?)",
                    ("proj-1", str(repo), "OrgPele", "envctl", "2026-05-20 15:00:00+00"),
                )
                connection.execute(
                    "insert into workspaces values (?, ?, ?, ?)",
                    ("ws-bridged", str(worktree), "feature/open", "2026-05-20 15:01:00+00"),
                )
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_PROJECT": "proj-1",
                    "HOME": str(home),
                    "ENVCTL_PLAN_AGENT_SUPERSET_DESKTOP_RESTART": "false",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/open\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps(
                            {
                                "workspace": {
                                    "id": "ws-bridged",
                                    "projectId": "proj-1",
                                    "hostId": "host-1",
                                    "organizationId": "org-1",
                                    "branch": "feature/open",
                                    "name": "feature-a-1",
                                    "createdByUserId": "user-1",
                                    "createdAt": "2026-05-20 15:01:00+00",
                                    "updatedAt": "2026-05-20 15:01:00+00",
                                }
                            }
                        ),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout="", stderr=""),
                ]
            )

            result = launch_plan_agent_terminals(
                rt,
                route=parse_route(["--plan", "feature-a"], env={}),
                created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
            )
            with sqlite3.connect(local_db) as connection:
                local_row = connection.execute(
                    "select project_id, worktree_id, type, branch, name from workspaces where id = 'ws-bridged'"
                ).fetchone()
            with sqlite3.connect(tanstack_db) as connection:
                cache_row = connection.execute(
                    "select value from c_workspaces_org_1 where key = 's:ws-bridged'"
                ).fetchone()

        self.assertEqual(result.status, "launched")
        self.assertEqual(local_row, ("proj-1", "ws-bridged", "worktree", "feature/open", "feature-a-1"))
        self.assertIsNotNone(cache_row)
        cached_payload = json.loads(cache_row[0])
        self.assertEqual(cached_payload["id"], "ws-bridged")
        self.assertEqual(cached_payload["projectId"], "proj-1")
        self.assertEqual(cached_payload["organizationId"], "org-1")
        bridge_events = self._events(rt, "planning.agent_launch.superset_desktop_bridge")
        self.assertEqual(len(bridge_events), 1)
        ready_events = self._events(rt, "planning.agent_launch.superset_desktop_workspace_ready")
        self.assertEqual(len(ready_events), 1)

    def test_superset_open_fails_when_desktop_cache_cannot_resolve_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = Path(tmpdir) / "runtime"
            home = Path(tmpdir) / "home"
            db_path = home / ".superset" / "local.db"
            worktree.mkdir(parents=True, exist_ok=True)
            db_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(db_path) as connection:
                connection.execute("create table workspaces (id text primary key)")
            rt = self._runtime(
                repo,
                runtime,
                env={
                    "SUPERSET_PROJECT": "proj-1",
                    "HOME": str(home),
                    "ENVCTL_PLAN_AGENT_SUPERSET_DESKTOP_VERIFY_TIMEOUT": "0",
                },
            )
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(args=["git"], returncode=0, stdout="feature/open\n", stderr=""),
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=0,
                        stdout=json.dumps({"workspace": {"id": "ws-missing"}}),
                        stderr="",
                    ),
                    subprocess.CompletedProcess(args=["superset"], returncode=0, stdout="", stderr=""),
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=worktree, plan_file="a.md"),),
                )

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "launch_failed")
        self.assertEqual(result.outcomes[0].status, "failed")
        self.assertIn("could not resolve", str(result.outcomes[0].reason))
        self.assertIn("could not resolve", buffer.getvalue())
        unavailable_events = self._events(rt, "planning.agent_launch.superset_desktop_workspace_unavailable")
        self.assertEqual(len(unavailable_events), 1)
        self.assertEqual(unavailable_events[0]["workspace_id"], "ws-missing")

    def test_superset_nonzero_exit_returns_failed_outcome_with_error_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"SUPERSET_WORKSPACE": "ws-existing"})
            rt.process_runner = _RecordingRunner(
                outputs=[
                    subprocess.CompletedProcess(
                        args=["superset"],
                        returncode=1,
                        stdout="host unavailable",
                        stderr="not logged in",
                    )
                ]
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                result = launch_plan_agent_terminals(
                    rt,
                    route=parse_route(["--plan", "feature-a"], env={}),
                    created_worktrees=(CreatedPlanWorktree(name="feature-a-1", root=repo, plan_file="a.md"),),
                )

        rendered = buffer.getvalue()
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.outcomes[0].status, "failed")
        self.assertIn("not logged in", str(result.outcomes[0].reason))
        self.assertIn("not logged in", rendered)

    def test_superset_review_launch_is_explicitly_unsupported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            repo.mkdir(parents=True, exist_ok=True)
            rt = self._runtime(repo, runtime, env={"SUPERSET_WORKSPACE": "ws-existing"})

            readiness = launch_support.review_agent_launch_readiness(rt)
            result = launch_support.launch_review_agent_terminal(
                rt,
                repo_root=repo,
                project_name="feature-a-1",
                project_root=repo,
            )

        self.assertFalse(readiness.ready)
        self.assertEqual(readiness.reason, "unsupported_superset_review_tab")
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.reason, "unsupported_superset_review_tab")


if __name__ == "__main__":
    unittest.main()
