# ruff: noqa: F401,F811
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
    workflow_build,
    workflow_prompt_support,
    workflow_review_support,
    workflow_runtime_support,
)
from envctl_engine.planning.plan_agent.models import _PlanAgentWorkflowStep, _WorkspaceLaunchTarget
from envctl_engine.planning.plan_agent_launch_support import CreatedPlanWorktree, launch_plan_agent_terminals
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord

_screen_looks_ready = terminal_screen._screen_looks_ready
_prompt_submit_screen_looks_ready = terminal_screen._prompt_submit_screen_looks_ready
_tab_title_for_worktree = workflow_build._tab_title_for_worktree
_build_plan_agent_workflow = cast(Any, workflow_build._build_plan_agent_workflow)
_finalization_instruction_text = cast(Any, workflow_build._finalization_instruction_text)
_first_cycle_completion_instruction_text = cast(Any, workflow_build._first_cycle_completion_instruction_text)
_intermediate_cycle_completion_instruction_text = cast(Any, workflow_build._intermediate_cycle_completion_instruction_text)
_browser_e2e_instruction_text = cast(Any, workflow_build._browser_e2e_instruction_text)
_pr_review_comments_instruction_text = cast(Any, workflow_build._pr_review_comments_instruction_text)
_wait_for_codex_queue_ready = cast(Any, cmux_transport._wait_for_codex_queue_ready)
_codex_goal_screen_looks_active = cast(Any, terminal_screen._codex_goal_screen_looks_active)
_workflow_step_prompt_text = cast(Any, workflow_prompt_support._workflow_step_prompt_text)
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


class PlanAgentLaunchSupportTestCase(unittest.TestCase):
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


__all__ = [name for name in globals() if not name.startswith("__")]
