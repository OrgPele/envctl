from __future__ import annotations

# ruff: noqa: F401,F403,F405
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from importlib import resources
from pathlib import Path
from typing import Any, Literal, Mapping

from envctl_engine.planning import planning_feature_name
from envctl_engine.config import EngineConfig, _apply_plan_agent_aliases
from envctl_engine.runtime.codex_tmux_support import (
    _attach_interactive,
    _completed_process_error_text as _tmux_completed_process_error_text,
    _run_probe as _run_tmux_probe,
    _sanitize_name as _sanitize_tmux_name,
    _tmux_session_exists,
)
from envctl_engine.runtime.prompt_install_support import (
    resolve_codex_direct_prompt_body,
    resolve_opencode_direct_prompt_body,
)
from envctl_engine.state.models import RunState
from envctl_engine.shared.parsing import parse_bool, parse_int_or_none

from envctl_engine.planning.plan_agent.constants import *
from envctl_engine.planning.plan_agent.models import *
from envctl_engine.planning.plan_agent.config import *

def _plan_selector_for_route(route: object, created_worktrees: tuple[CreatedPlanWorktree, ...]) -> str:
    route_passthrough = list(getattr(route, "passthrough_args", []) or [])
    if route_passthrough:
        selector = str(route_passthrough[0]).strip()
        if selector:
            return selector
    route_projects = list(getattr(route, "projects", []) or [])
    if route_projects:
        selector = str(route_projects[0]).strip()
        if selector:
            return selector
    if created_worktrees:
        plan_file = str(created_worktrees[0].plan_file or "").strip()
        if plan_file:
            return plan_file.removesuffix(".md")
    return ""


def plan_agent_native_recovery_command(
    runtime: Any,
    *,
    route: object,
    launch_config: PlanAgentLaunchConfig,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
) -> tuple[str, ...]:
    selector = _plan_selector_for_route(route, created_worktrees)
    if not selector:
        return ()
    command: list[str] = []
    if launch_config.codex_cycles > 0:
        command.append(f"ENVCTL_PLAN_AGENT_CODEX_CYCLES={launch_config.codex_cycles}")
    repo_root = Path(
        str(
            getattr(runtime, "env", {}).get("RUN_REPO_ROOT")
            or getattr(getattr(runtime, "config", None), "raw", {}).get("RUN_REPO_ROOT")
            or runtime.config.base_dir
        )
    )
    command.extend(
        [
            "ENVCTL_USE_REPO_WRAPPER=1",
            _cli_display_path(repo_root / "bin" / "envctl"),
            "--plan",
            selector,
            "--tmux",
        ]
    )
    if launch_config.cli == "opencode":
        command.append("--opencode")
    elif launch_config.cli == "codex":
        command.append("--codex")
    route_flags = getattr(route, "flags", {}) or {}
    scope_token_by_value = {
        "backend": "--backend",
        "frontend": "--frontend",
        "fullstack": "--fullstack",
        "dependencies": "--dependencies",
        "entire-system": "--entire-system",
    }
    scope_token = scope_token_by_value.get(str(route_flags.get("runtime_scope") or ""))
    if scope_token:
        command.append(scope_token)
    launch_backend = route_flags.get("launch_backend")
    launch_frontend = route_flags.get("launch_frontend")
    launch_dependencies = route_flags.get("launch_dependencies")
    if launch_backend is False and launch_frontend is False and launch_dependencies is False:
        command.append("--no-infra")
    elif launch_backend is True and launch_frontend is False and launch_dependencies is False:
        command.append("--only-backend")
    elif launch_backend is False and launch_frontend is True and launch_dependencies is False:
        command.append("--only-frontend")
    elif launch_dependencies is False:
        command.append("--no-deps")
    dependency_scope = str(route_flags.get("dependency_scope") or "").strip()
    if dependency_scope == "shared":
        command.append("--shared-deps")
    elif dependency_scope == "isolated":
        command.append("--isolated-deps")
    if bool(route_flags.get("batch") or route_flags.get("default_headless")):
        command.append("--headless")
    command.append("--new-session")
    return tuple(command)


def _cli_display_path(path: Path) -> str:
    raw = str(path)
    if raw.startswith("/private/var/"):
        return raw.removeprefix("/private")
    return raw


def _plan_agent_recovery_command_text(command: tuple[str, ...]) -> str:
    return shlex.join(command) if command else ""


def _new_session_command_for_route(
    runtime: Any,
    *,
    route: object,
    launch_config: PlanAgentLaunchConfig,
    created_worktrees: tuple[CreatedPlanWorktree, ...],
) -> tuple[str, ...]:
    selector = _plan_selector_for_route(route, created_worktrees)
    if not selector:
        return ()
    command = [
        "ENVCTL_USE_REPO_WRAPPER=1",
        str(Path(runtime.config.base_dir).resolve() / "bin" / "envctl"),
        "--plan",
        selector,
        "--omx" if launch_config.transport == "omx" else "--tmux",
    ]
    if launch_config.cli == "opencode":
        command.append("--opencode")
    elif launch_config.cli == "codex":
        command.append("--codex")
    route_flags = getattr(route, "flags", {}) or {}
    workflow_tokens = (("ultragoal", "--ultragoal"), ("ralph", "--ralph"), ("team", "--team"), ("ulw", "--ulw"))
    for flag_name, token in workflow_tokens:
        if bool(route_flags.get(flag_name)):
            command.append(token)
    command.append("--new-session")
    command.append("--headless")
    return tuple(command)


def _summarize_failed_launch_outcomes(outcomes: list[PlanAgentLaunchOutcome], *, limit: int = 2) -> str:
    details: list[str] = []
    for item in outcomes[:limit]:
        reason = str(item.reason or "").strip()
        if not reason:
            continue
        details.append(f"{item.worktree_name}: {reason}")
    if not details:
        return ""
    suffix = "" if len(outcomes) <= limit else f"; +{len(outcomes) - limit} more"
    return "; ".join(details) + suffix


def _queue_failure_event_context(reason: str) -> dict[str, object]:
    context: dict[str, object] = {}
    step_index = getattr(reason, "step_index", None)
    if step_index is not None:
        context["queue_failed_step_index"] = step_index
    step_kind = getattr(reason, "step_kind", None)
    if step_kind:
        context["queue_failed_step_kind"] = step_kind
    return context


def _print_launch_summary(message: str) -> None:
    print(message)


def _persist_runtime_events_snapshot(runtime: Any) -> None:
    persist = getattr(runtime, "_persist_events_snapshot", None)
    if not callable(persist):
        return
    try:
        persist()
    except Exception:
        return


__all__ = tuple(name for name in globals() if not name.startswith("__"))
