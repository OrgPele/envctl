from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from envctl_engine.actions.action_command_support import build_action_extra_env
from envctl_engine.actions.action_target_support import ActionTargetIdentity, action_target_identities
from envctl_engine.actions.project_action_domain import ActionProjectContext, run_ship_action
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
    for identity in identities:
        code = run_ship_on_pass_for_identity(orchestrator, route, targets, identity, message=message)
        if code != 0:
            return code
    return 0


def run_ship_on_pass_for_identity(
    orchestrator: Any,
    route: Route,
    targets: list[object],
    identity: ActionTargetIdentity,
    *,
    message: str,
) -> int:
    runtime = getattr(orchestrator, "runtime")
    ship_route = Route(
        command="ship",
        mode=route.mode,
        raw_args=list(getattr(route, "raw_args", [])),
        passthrough_args=[],
        projects=[identity.name],
        flags={"commit_message": message, **({"human": True} if route.flags.get("human") else {})},
    )
    context = ActionProjectContext(
        repo_root=Path(runtime.config.base_dir).resolve(),
        project_root=identity.root.resolve(),
        project_name=identity.name,
        env=_ship_env(orchestrator, runtime, ship_route, targets, identity),
    )
    return run_ship_action(context)


def _ship_env(
    orchestrator: Any,
    runtime: Any,
    ship_route: Route,
    targets: list[object],
    identity: ActionTargetIdentity,
) -> Mapping[str, str]:
    extra_builder = getattr(orchestrator, "ship_action_extra_env", None)
    extra = dict(extra_builder(ship_route) if callable(extra_builder) else build_action_extra_env(ship_route))
    env_builder = getattr(orchestrator, "action_env", None)
    if callable(env_builder):
        return env_builder("ship", targets, route=ship_route, target=identity.target_obj, extra=extra)
    env = dict(getattr(runtime, "env", {}))
    env.update(extra)
    return {str(key): str(value) for key, value in env.items()}
