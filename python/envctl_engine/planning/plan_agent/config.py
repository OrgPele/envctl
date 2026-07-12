from __future__ import annotations

# ruff: noqa: F401
import shutil
from typing import Any

from envctl_engine.config import EngineConfig, _apply_plan_agent_aliases

from envctl_engine.planning.plan_agent.launch_policy import (
    PlanAgentLaunchPolicy,
    cli_ready_delay_seconds,
    codex_tui_queue_workflow_supported,
    command_executable,
    default_plan_agent_cli_command,
    default_plan_agent_surface_transport,
    guidance_attach_command,
    missing_launch_commands,
    normalize_plan_agent_surface_transport,
    parse_codex_cycles,
    uses_direct_submission,
)
from envctl_engine.planning.plan_agent.models import PlanAgentLaunchConfig


def _launch_policy(
    config: EngineConfig,
    env: dict[str, str] | None = None,
    *,
    route: object | None = None,
) -> PlanAgentLaunchPolicy:
    env_map = dict(env or {})
    _apply_plan_agent_aliases(env_map, explicit_values=env_map)
    return PlanAgentLaunchPolicy(
        config=config,
        env=env_map,
        route=route,
        command_available=shutil.which,
    )


def _codex_tui_queue_workflow_supported(launch_config: PlanAgentLaunchConfig) -> bool:
    return codex_tui_queue_workflow_supported(launch_config)


def _uses_direct_submission(*, cli: str, direct_prompt_enabled: bool) -> bool:
    return uses_direct_submission(cli=cli, direct_prompt_enabled=direct_prompt_enabled)


def _cli_ready_delay_seconds(cli: str) -> float:
    return cli_ready_delay_seconds(cli)


def resolve_plan_agent_launch_config(
    config: EngineConfig,
    env: dict[str, str] | None = None,
    *,
    route: object | None = None,
) -> PlanAgentLaunchConfig:
    return _launch_policy(config, env, route=route).resolve_launch_config()


def _route_requests_ulw(route: object | None) -> bool:
    return bool(getattr(route, "flags", {}).get("ulw"))


def _ulw_route_supported(*, launch_config: PlanAgentLaunchConfig) -> bool:
    return PlanAgentLaunchPolicy.ulw_route_supported(launch_config)


def _guidance_attach_command(session_name: str) -> tuple[str, ...]:
    return guidance_attach_command(session_name)


def plan_agent_launch_prereq_commands(
    config: EngineConfig,
    env: dict[str, str] | None = None,
    *,
    route: object | None = None,
) -> tuple[str, ...]:
    return _launch_policy(config, env, route=route).prereq_commands()


def _missing_launch_commands(runtime: Any, launch_config: PlanAgentLaunchConfig) -> list[str]:
    return missing_launch_commands(runtime, launch_config)


__all__ = tuple(name for name in globals() if not name.startswith("__"))
