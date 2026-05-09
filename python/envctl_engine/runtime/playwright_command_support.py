from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.endpoints_command_support import build_endpoints_payload
from envctl_engine.state.project_runtime import (
    active_project_names,
    project_resolution_event_payload,
    project_root_for_state,
    resolve_requested_project_state,
)


def run_playwright_command(runtime: Any, route: Route) -> int:
    json_output = bool(getattr(route, "flags", {}).get("json"))
    command = [str(arg) for arg in getattr(route, "passthrough_args", []) if str(arg)]
    if not command:
        return _emit(
            {"ok": False, "error": "playwright requires a command after --"},
            json_output=json_output,
            ok=False,
        )
    state = _load_state(runtime, route)
    if state is None:
        return _emit({"ok": False, "error": "state_not_found"}, json_output=json_output, ok=False)
    requested_projects = list(getattr(route, "projects", []) or [])
    active_projects = active_project_names(state, runtime=runtime)
    if not requested_projects and len(active_projects) != 1:
        return _emit(
            {"ok": False, "error": "project_required", "active_projects": active_projects},
            json_output=json_output,
            ok=False,
        )
    resolution = resolve_requested_project_state(
        state,
        requested_projects,
        command="playwright",
        runtime=runtime,
        allow_multi=False,
    )
    if not resolution.ok:
        _emit_resolution(runtime, "state.project_resolution.failed", resolution, state)
        return _emit(resolution.payload(), json_output=json_output, ok=False)
    _emit_resolution(runtime, "state.project_resolution.ok", resolution, state)
    project = resolution.selected_projects[0] if resolution.selected_projects else ""
    selected_state = resolution.state or state
    endpoints = build_endpoints_payload(
        selected_state,
        project=project,
        env=getattr(runtime, "env", {}),
        config=getattr(runtime, "config", None),
        runtime=runtime,
    )
    frontend = endpoints.get("frontend") if isinstance(endpoints.get("frontend"), dict) else {}
    selected_url = str(frontend.get("public_url") or frontend.get("local_url") or "").strip()
    if not selected_url:
        return _emit(
            {"ok": False, "error": "frontend_not_running", "project": project, "run_id": state.run_id},
            json_output=json_output,
            ok=False,
        )
    cwd = Path(str(project_root_for_state(selected_state, project, runtime=runtime) or ".")).resolve()
    env = dict(os.environ)
    env.update({str(key): str(value) for key, value in (getattr(runtime, "env", {}) or {}).items()})
    metadata_path = _metadata_path(runtime, state.run_id)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    endpoints_path = metadata_path.with_name("playwright-endpoints.json")
    try:
        endpoints_path.write_text(json.dumps(endpoints, indent=2, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        return _emit(
            {"ok": False, "error": "endpoints_artifact_write_failed", "detail": str(exc)},
            json_output=json_output,
            ok=False,
        )
    env.update(
        {
            "QA_BASE_URL": selected_url,
            "BASE_URL": selected_url,
            "ENVCTL_PROJECT_NAME": project,
            "ENVCTL_RUN_ID": state.run_id,
            "ENVCTL_RUNTIME_MODE": state.mode,
            "ENVCTL_DEPENDENCY_MODE": str(endpoints.get("dependency_mode") or "unknown"),
            "ENVCTL_ENDPOINTS_JSON": str(endpoints_path),
            "ENVCTL_ENDPOINTS_JSON_PATH": str(endpoints_path),
        }
    )
    runner = getattr(runtime, "process_runner", None)
    run = getattr(runner, "run", None)
    if not callable(run):
        return _emit({"ok": False, "error": "process_runner_unavailable"}, json_output=json_output, ok=False)
    completed = run(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL)
    exit_code = int(getattr(completed, "returncode", 1) or 0)
    metadata = {
        "project": project,
        "run_id": state.run_id,
        "mode": state.mode,
        "command": command,
        "cwd": str(cwd),
        "selected_url": selected_url,
        "endpoints_path": str(endpoints_path),
        "endpoints": endpoints,
        "exit_code": exit_code,
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    payload = {
        "ok": exit_code == 0,
        "project": project,
        "run_id": state.run_id,
        "selected_url": selected_url,
        "metadata_path": str(metadata_path),
        "endpoints_path": str(endpoints_path),
        "exit_code": exit_code,
    }
    return _emit(payload, json_output=json_output, ok=exit_code == 0)



def _emit_resolution(runtime: Any, event: str, resolution: Any, state: Any) -> None:
    emitter = getattr(runtime, "_emit", None)
    if not callable(emitter):
        return
    emitter(event, **project_resolution_event_payload(resolution, state, runtime=runtime))

def _metadata_path(runtime: Any, run_id: str) -> Path:
    repository = getattr(runtime, "state_repository", None)
    test_results = getattr(repository, "test_results_dir_path", None)
    if callable(test_results):
        return Path(test_results(run_id)) / "playwright-runtime-metadata.json"
    runtime_root = Path(getattr(runtime, "runtime_root", "."))
    return runtime_root / "runs" / run_id / "test-results" / "playwright-runtime-metadata.json"


def _load_state(runtime: Any, route: Route):  # noqa: ANN201
    loader = getattr(runtime, "_try_load_existing_state", None)
    if not callable(loader):
        return None
    strict = False
    strict_resolver = getattr(runtime, "_state_lookup_strict_mode_match", None)
    if callable(strict_resolver):
        strict = bool(strict_resolver(route))
    return loader(mode=getattr(route, "mode", None), strict_mode_match=strict)


def _emit(payload: dict[str, object], *, json_output: bool, ok: bool) -> int:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif ok:
        print(str(payload.get("selected_url") or "ok"))
    else:
        print(str(payload.get("error") or "playwright failed"))
    return 0 if ok else 1
