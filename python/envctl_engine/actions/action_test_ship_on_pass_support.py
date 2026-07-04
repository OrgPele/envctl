from __future__ import annotations

from typing import Any

from envctl_engine.actions.action_target_support import ActionTargetIdentity, action_target_identities
from envctl_engine.runtime.command_router import Route


def ship_on_pass_message(route: Route, *, dry_run: bool = False, json_output: bool = False) -> tuple[str | None, int]:
    raw = route.flags.get("ship_on_pass")
    if raw is None:
        return None, 0
    message = str(raw).strip()
    if not message:
        print("error: --ship-on-pass requires a non-empty message.")
        return None, 1
    if dry_run:
        print("error: --ship-on-pass cannot be used with --dry-run because no tests are executed.")
        return None, 1
    if json_output:
        print("error: --ship-on-pass cannot be used with --json because combined JSON output would be ambiguous.")
        return None, 1
    return message, 0


def run_ship_on_pass_for_targets(orchestrator: Any, route: Route, targets: list[object], *, message: str) -> int:
    identities = action_target_identities(targets)
    if not identities:
        print("error: --ship-on-pass could not resolve a target to ship.")
        return 1
    ship_action = getattr(orchestrator, "run_ship_action", None)
    if not callable(ship_action):
        print("error: --ship-on-pass requires the normal ship action path.")
        return 1
    ship_targets = [identity.target_obj for identity in identities]
    ship_route = _ship_route(route, project_names=[identity.name for identity in identities], message=message)
    return int(ship_action(ship_route, ship_targets))


def run_ship_on_pass_for_identity(
    orchestrator: Any,
    route: Route,
    targets: list[object],
    identity: ActionTargetIdentity,
    *,
    message: str,
) -> int:
    return run_ship_on_pass_for_targets(orchestrator, route, [identity.target_obj], message=message)


def successful_outcome_targets(targets: list[object], outcomes: list[dict[str, object]]) -> list[object]:
    successful_names = {
        str(item.get("project_name", "")).strip()
        for item in outcomes
        if _outcome_returncode(item.get("returncode")) == 0 and str(item.get("project_name", "")).strip()
    }
    if not successful_names:
        return []
    return [identity.target_obj for identity in action_target_identities(targets) if identity.name in successful_names]


def _ship_route(route: Route, *, project_names: list[str], message: str) -> Route:
    flags = dict(route.flags)
    flags.pop("ship_on_pass", None)
    flags.pop("dry_run", None)
    flags["commit_message"] = message
    return Route(
        command="ship",
        mode=route.mode,
        raw_args=list(getattr(route, "raw_args", [])),
        passthrough_args=[],
        projects=project_names,
        flags=flags,
    )


def _outcome_returncode(value: object) -> int:
    try:
        return int(value if value is not None else 1)
    except (TypeError, ValueError):
        return 1
