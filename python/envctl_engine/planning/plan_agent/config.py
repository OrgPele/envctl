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
from envctl_engine.planning.plan_agent.intent import resolve_plan_agent_launch_intent
from envctl_engine.planning.plan_agent.models import *

def _parse_codex_cycles(raw: object) -> tuple[int, str | None]:
    normalized = str(raw or "").strip()
    if not normalized:
        return 0, None
    value = parse_int_or_none(normalized)
    if value is None:
        return 0, "invalid_codex_cycles"
    if value < 0:
        return 0, "invalid_codex_cycles"
    if value > _PLAN_AGENT_CODEX_CYCLE_CAP:
        return _PLAN_AGENT_CODEX_CYCLE_CAP, "bounded_codex_cycles"
    return value, None


def _workflow_mode_for_launch_config(launch_config: PlanAgentLaunchConfig) -> str:
    if _codex_tui_queue_workflow_supported(launch_config) and launch_config.codex_cycles > 0:
        return _PLAN_AGENT_WORKFLOW_CODEX_CYCLES
    return _PLAN_AGENT_WORKFLOW_SINGLE_PROMPT


def _codex_tui_queue_workflow_supported(launch_config: PlanAgentLaunchConfig) -> bool:
    return launch_config.cli == "codex" and launch_config.transport in {"cmux", "tmux", "omx"}


def _uses_direct_submission(*, cli: str, direct_prompt_enabled: bool) -> bool:
    normalized_cli = str(cli).strip().lower()
    if normalized_cli == "codex":
        return True
    return normalized_cli == "opencode" and direct_prompt_enabled


def _cli_ready_delay_seconds(cli: str) -> float:
    return _CLI_READY_DELAY_SECONDS_BY_CLI.get(str(cli).strip().lower(), _DEFAULT_CLI_READY_DELAY_SECONDS)


def resolve_plan_agent_launch_config(
    config: EngineConfig,
    env: dict[str, str] | None = None,
    *,
    route: object | None = None,
) -> PlanAgentLaunchConfig:
    env_map = dict(env or {})
    _apply_plan_agent_aliases(env_map, explicit_values=env_map)
    route_flags = getattr(route, "flags", {}) or {}
    launch_intent = resolve_plan_agent_launch_intent(env_map=env_map, config_raw=config.raw, route=route)
    transport = launch_intent.transport
    cli = launch_intent.cli
    codex_yolo_enabled = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_CODEX_YOLO")
        or config.raw.get("ENVCTL_PLAN_AGENT_CODEX_YOLO"),
        True,
    )
    cli_command = str(
        env_map.get("ENVCTL_PLAN_AGENT_CLI_CMD")
        or config.raw.get("ENVCTL_PLAN_AGENT_CLI_CMD")
        or _default_plan_agent_cli_command(cli, codex_yolo_enabled=codex_yolo_enabled)
    ).strip() or cli
    preset = str(
        env_map.get("ENVCTL_PLAN_AGENT_PRESET")
        or config.raw.get("ENVCTL_PLAN_AGENT_PRESET")
        or _DEFAULT_PRESET
    ).strip() or _DEFAULT_PRESET
    shell = str(
        env_map.get("ENVCTL_PLAN_AGENT_SHELL")
        or config.raw.get("ENVCTL_PLAN_AGENT_SHELL")
        or _DEFAULT_SHELL
    ).strip() or _DEFAULT_SHELL
    cmux_workspace = str(
        env_map.get("ENVCTL_PLAN_AGENT_CMUX_WORKSPACE")
        or config.raw.get("ENVCTL_PLAN_AGENT_CMUX_WORKSPACE")
        or ""
    ).strip()
    superset_project = str(
        env_map.get("ENVCTL_PLAN_AGENT_SUPERSET_PROJECT")
        or config.raw.get("ENVCTL_PLAN_AGENT_SUPERSET_PROJECT")
        or ""
    ).strip()
    superset_workspace = str(
        env_map.get("ENVCTL_PLAN_AGENT_SUPERSET_WORKSPACE")
        or config.raw.get("ENVCTL_PLAN_AGENT_SUPERSET_WORKSPACE")
        or ""
    ).strip()
    superset_host = str(
        env_map.get("ENVCTL_PLAN_AGENT_SUPERSET_HOST")
        or config.raw.get("ENVCTL_PLAN_AGENT_SUPERSET_HOST")
        or ""
    ).strip()
    codex_cycles, codex_cycles_warning = _parse_codex_cycles(
        env_map.get("ENVCTL_PLAN_AGENT_CODEX_CYCLES")
        or config.raw.get("ENVCTL_PLAN_AGENT_CODEX_CYCLES")
        or ""
    )
    enabled = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_TERMINALS_ENABLE")
        or config.raw.get("ENVCTL_PLAN_AGENT_TERMINALS_ENABLE"),
        False,
    ) or any(
        (
            bool(cmux_workspace),
            launch_intent.route_launch_requested,
            bool(superset_project or superset_workspace),
            transport in {"tmux", "omx"},
        )
    )
    direct_prompt_enabled = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_DIRECT_PROMPT")
        or config.raw.get("ENVCTL_PLAN_AGENT_DIRECT_PROMPT"),
        True if cli == "opencode" else False,
    )
    ulw_loop_prefix = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_ULW_LOOP_PREFIX")
        or config.raw.get("ENVCTL_PLAN_AGENT_ULW_LOOP_PREFIX"),
        True if (cli == "opencode" and direct_prompt_enabled) else False,
    )
    ulw_suffix = parse_bool(
        env_map.get("ENVCTL_PLAN_AGENT_APPEND_ULW")
        or config.raw.get("ENVCTL_PLAN_AGENT_APPEND_ULW"),
        False,
    )
    if bool(route_flags.get("ulw")):
        ulw_loop_prefix = True
        if cli == "opencode":
            direct_prompt_enabled = True
    if bool(route_flags.get("no_ulw_loop")):
        ulw_loop_prefix = False
    omx_workflow: Literal["", "ultragoal", "ralph", "team"] = ""
    if bool(route_flags.get("ultragoal")):
        omx_workflow = "ultragoal"
    elif bool(route_flags.get("ralph")):
        omx_workflow = "ralph"
    elif bool(route_flags.get("team")):
        omx_workflow = "team"
    goal_enabled = False
    if cli == "codex":
        goal_enabled = parse_bool(
            env_map.get("ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE")
            or config.raw.get("ENVCTL_PLAN_AGENT_CODEX_GOAL_ENABLE"),
            True,
        )
        if bool(route_flags.get("goal")) or bool(route_flags.get("codex_goal")):
            goal_enabled = True
        if bool(route_flags.get("no_goal")) or bool(route_flags.get("no_codex_goal")):
            goal_enabled = False
    return PlanAgentLaunchConfig(
        enabled=enabled,
        transport=transport,
        cli=cli,
        cli_command=cli_command,
        preset=preset,
        codex_cycles=codex_cycles,
        codex_cycles_warning=codex_cycles_warning,
        browser_e2e_followup_enable=parse_bool(
            env_map.get("ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE")
            or config.raw.get("ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE"),
            True,
        ),
        pr_review_comments_followup_enable=parse_bool(
            env_map.get("ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE")
            or config.raw.get("ENVCTL_PLAN_AGENT_PR_REVIEW_COMMENTS_ENABLE"),
            True,
        ),
        shell=shell,
        require_cmux_context=parse_bool(
            env_map.get("ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT")
            or config.raw.get("ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT"),
            True,
        ),
        cmux_workspace=cmux_workspace,
        direct_prompt_enabled=direct_prompt_enabled,
        ulw_loop_prefix=ulw_loop_prefix,
        ulw_suffix=ulw_suffix,
        omx_workflow=omx_workflow,
        codex_goal_enable=goal_enabled,
        superset_project=superset_project,
        superset_workspace=superset_workspace,
        superset_host=superset_host,
        superset_local=parse_bool(
            env_map.get("ENVCTL_PLAN_AGENT_SUPERSET_LOCAL")
            or config.raw.get("ENVCTL_PLAN_AGENT_SUPERSET_LOCAL"),
            True,
        ),
        superset_open=parse_bool(
            env_map.get("ENVCTL_PLAN_AGENT_SUPERSET_OPEN")
            or config.raw.get("ENVCTL_PLAN_AGENT_SUPERSET_OPEN"),
            True,
        ),
        surface_transport_warning=launch_intent.surface_transport_warning,
    )


def _default_plan_agent_cli_command(cli: str, *, codex_yolo_enabled: bool = True) -> str:
    normalized = str(cli).strip().lower()
    if normalized == "codex":
        if codex_yolo_enabled:
            return f"codex {_CODEX_BYPASS_FLAGS}"
        return "codex"
    return normalized or "codex"


def _route_requests_ulw(route: object | None) -> bool:
    return bool(getattr(route, "flags", {}).get("ulw"))


def _ulw_route_supported(*, launch_config: PlanAgentLaunchConfig) -> bool:
    return launch_config.cli == "opencode"


def _guidance_attach_command(session_name: str) -> tuple[str, ...]:
    return ("tmux", "attach", "-t", session_name)


def plan_agent_launch_prereq_commands(
    config: EngineConfig,
    env: dict[str, str] | None = None,
    *,
    route: object | None = None,
) -> tuple[str, ...]:
    launch_config = resolve_plan_agent_launch_config(config, env, route=route)
    if not launch_config.enabled:
        return ()
    if launch_config.surface_transport_warning:
        return ()
    if launch_config.transport == "omx":
        return ("omx", "tmux", "script", "codex")
    if launch_config.transport == "superset":
        return ("superset", "codex")
    cli_executable = _command_executable(launch_config.cli_command)
    launcher = "tmux" if launch_config.transport == "tmux" else "cmux"
    if not cli_executable:
        return (launcher,)
    return (launcher, cli_executable)


def _command_executable(raw_command: str) -> str | None:
    try:
        parsed = shlex.split(raw_command)
    except ValueError:
        return None
    if not parsed:
        return None
    return str(parsed[0]).strip() or None


def _missing_launch_commands(runtime: Any, launch_config: PlanAgentLaunchConfig) -> list[str]:
    if launch_config.transport == "omx":
        required = ["omx", "tmux", "script", "codex"]
    elif launch_config.transport == "superset":
        required = ["superset", "codex"]
    else:
        required = ["tmux" if launch_config.transport == "tmux" else "cmux"]
        cli_executable = _command_executable(launch_config.cli_command)
        shell_executable = _command_executable(launch_config.shell)
        if cli_executable:
            required.append(cli_executable)
        if shell_executable:
            required.append(shell_executable)
        if launch_config.cli not in _SUPPORTED_PLAN_AGENT_CLIS and not _command_executable(launch_config.cli_command):
            required.append(launch_config.cli)
    missing: list[str] = []
    for command in required:
        if command in missing:
            continue
        if runtime._command_exists(command):
            continue
        missing.append(command)
    return missing


__all__ = tuple(name for name in globals() if not name.startswith("__"))
