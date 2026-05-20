from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping


PlanAgentTransport = Literal["cmux", "tmux", "omx", "superset"]
PlanAgentReadinessExpectation = Literal["cmux_context", "tmux_cli", "omx_session", "superset_workspace"]


@dataclass(slots=True, frozen=True)
class PlanAgentLaunchIntent:
    transport: PlanAgentTransport
    cli: str
    readiness_expectation: PlanAgentReadinessExpectation
    route_launch_requested: bool
    surface_transport_warning: str | None = None


def resolve_plan_agent_launch_intent(
    *,
    env_map: Mapping[str, str],
    config_raw: Mapping[str, object],
    route: object | None,
) -> PlanAgentLaunchIntent:
    route_flags = getattr(route, "flags", {}) or {}
    cmux_launch_requested = bool(route_flags.get("cmux"))
    opencode_launch_requested = bool(route_flags.get("opencode"))
    configured_surface_transport = _configured_surface_transport(env_map=env_map, config_raw=config_raw)
    surface_transport_warning = None
    if configured_surface_transport not in {"cmux", "superset"}:
        surface_transport_warning = "invalid_surface_transport"
        configured_surface_transport = "cmux"

    if bool(route_flags.get("omx")):
        transport: PlanAgentTransport = "omx"
    elif bool(route_flags.get("tmux")):
        transport = "tmux"
    elif cmux_launch_requested:
        transport = "cmux"
    elif opencode_launch_requested:
        transport = "tmux"
    else:
        transport = "superset" if configured_surface_transport == "superset" else "cmux"

    cli = _selected_cli(
        env_map=env_map,
        config_raw=config_raw,
        route_flags=route_flags,
        transport=transport,
    )
    return PlanAgentLaunchIntent(
        transport=transport,
        cli=cli,
        readiness_expectation=_readiness_expectation_for_transport(transport),
        route_launch_requested=cmux_launch_requested
        or opencode_launch_requested
        or bool(route_flags.get("tmux"))
        or bool(route_flags.get("omx")),
        surface_transport_warning=surface_transport_warning,
    )


def _configured_surface_transport(*, env_map: Mapping[str, str], config_raw: Mapping[str, object]) -> str:
    return str(
        env_map.get("ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT")
        or config_raw.get("ENVCTL_PLAN_AGENT_SURFACE_TRANSPORT")
        or "cmux"
    ).strip().lower() or "cmux"


def _selected_cli(
    *,
    env_map: Mapping[str, str],
    config_raw: Mapping[str, object],
    route_flags: Mapping[str, object],
    transport: PlanAgentTransport,
) -> str:
    if bool(route_flags.get("opencode")):
        raw_cli: object = "opencode"
    elif bool(route_flags.get("codex")) or transport == "omx":
        raw_cli = "codex"
    else:
        raw_cli = env_map.get("ENVCTL_PLAN_AGENT_CLI") or config_raw.get("ENVCTL_PLAN_AGENT_CLI") or "codex"
    return str(raw_cli).strip().lower() or "codex"


def _readiness_expectation_for_transport(transport: PlanAgentTransport) -> PlanAgentReadinessExpectation:
    if transport == "tmux":
        return "tmux_cli"
    if transport == "omx":
        return "omx_session"
    if transport == "superset":
        return "superset_workspace"
    return "cmux_context"


__all__ = tuple(name for name in globals() if not name.startswith("__"))
