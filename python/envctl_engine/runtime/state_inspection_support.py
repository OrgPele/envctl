from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.state import state_to_dict
from envctl_engine.state.lookup import call_state_loader
from envctl_engine.state.models import RunState
from envctl_engine.state.project_runtime import (
    cwd_runtime_warnings,
    dependency_mode_summary,
    project_resolution_event_payload,
    resolve_requested_project_state,
)
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.ui.path_links import render_path_for_terminal

StateLoader = Callable[..., RunState | None]
WarningEmitter = Callable[..., None]


def print_state(
    runtime: Any,
    route: Route,
    *,
    json_output: bool,
    state_loader: StateLoader,
    warning_emitter: WarningEmitter,
) -> int:
    strict = runtime._state_lookup_strict_mode_match(route)
    requested_projects = list(getattr(route, "projects", []) or [])
    state = state_loader(
        runtime,
        mode=route.mode,
        strict_mode_match=strict,
        project_names=requested_projects or None,
    )
    if state is None and requested_projects:
        # A targeted repository lookup correctly returns no owner for an
        # unknown project. Load the mode-wide aggregate once so the command can
        # distinguish that case from an entirely missing runtime and return the
        # structured requested_project_not_running contract.
        state = state_loader(
            runtime,
            mode=route.mode,
            strict_mode_match=strict,
            project_names=None,
        )
    if state is None:
        if json_output:
            print(json.dumps({"found": False, "mode": getattr(route, "mode", None)}, indent=2, sort_keys=True))
        else:
            print("No previous state found.")
        return 1
    if requested_projects:
        resolution = resolve_requested_project_state(
            state,
            requested_projects,
            command="show-state",
            runtime=runtime,
            allow_multi=False,
        )
        if not resolution.ok:
            _emit_project_resolution(runtime, "state.project_resolution.failed", resolution, state)
            if json_output:
                print(json.dumps(resolution.payload(), indent=2, sort_keys=True))
            else:
                print(f"Requested project is not running: {resolution.requested_project}")
                print("Active runtime projects: " + (", ".join(resolution.active_projects) or "none"))
            return 1
        _emit_project_resolution(runtime, "state.project_resolution.ok", resolution, state)
        if resolution.state is not None and not bool(getattr(route, "flags", {}).get("all")):
            state = resolution.state

    dependency_summary = dependency_mode_summary(state)
    cwd_project, warnings = cwd_runtime_warnings(
        state,
        runtime=runtime,
        requested_projects=list(getattr(route, "projects", []) or []),
    )
    warning_emitter(runtime, command="show-state", state=state, warnings=warnings)
    payload: dict[str, Any] = {
        "found": True,
        "runtime_root": str(runtime.runtime_root),
        "run_state_path": str(runtime._run_state_path()),
        "state": state_to_dict(state),
        "runtime_map": build_runtime_map(state),
        "dependency_mode": dependency_summary["dependency_mode"],
        "shared_dependencies": dependency_summary["shared_dependencies"],
        "cwd_project": cwd_project,
        "warnings": warnings,
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    state_payload = payload["state"]
    print(f"run_id: {state_payload['run_id']}")
    print(f"mode: {state_payload['mode']}")
    print(f"services: {len(state_payload['services'])}")
    print(f"requirements: {len(state_payload['requirements'])}")
    for warning in warnings:
        print(f"Warning: {warning['message']}")
    print("run_state_path:")
    print(render_path_for_terminal(payload["run_state_path"], env=getattr(runtime, "env", {})))
    return 0


def try_load_existing_state(
    runtime: Any,
    *,
    mode: str | None,
    strict_mode_match: bool,
    project_names: list[str] | None = None,
) -> RunState | None:
    loader = getattr(runtime, "_try_load_existing_state", None)
    if not callable(loader):
        return None
    state = call_state_loader(
        loader,
        mode=mode,
        strict_mode_match=strict_mode_match,
        project_names=project_names,
    )
    return state if isinstance(state, RunState) else None


def emit_cwd_runtime_mismatch_warnings(
    runtime: Any,
    *,
    command: str,
    state: RunState,
    warnings: list[dict[str, object]],
) -> None:
    emitter = getattr(runtime, "_emit", None)
    if not callable(emitter):
        return
    for warning in warnings:
        if str(warning.get("code") or "") != "cwd_runtime_mismatch":
            continue
        emitter(
            "state.cwd_runtime_mismatch",
            run_id=getattr(state, "run_id", ""),
            mode=getattr(state, "mode", ""),
            command=command,
            cwd_project=warning.get("cwd_project"),
            active_projects=warning.get("active_projects"),
        )


def _emit_project_resolution(runtime: Any, event: str, resolution: Any, state: RunState) -> None:
    emitter = getattr(runtime, "_emit", None)
    if callable(emitter):
        emitter(
            event,
            **project_resolution_event_payload(resolution, state, runtime=runtime),
        )
