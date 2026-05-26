from __future__ import annotations

import concurrent.futures
import json
import sys
from pathlib import Path
from typing import Any

from envctl_engine.config import discover_local_config_state
from envctl_engine.config.persistence import managed_values_from_local_state, managed_values_to_payload
from envctl_engine.planning import PlanProjectPrediction
from envctl_engine.runtime.command_router import Route, list_supported_commands
from envctl_engine.startup.startup_selection_support import (
    _state_project_names as _state_project_names_impl,
    _tree_preselected_projects_from_state as _tree_preselected_projects_from_state_impl,
)
from envctl_engine.ui.path_links import render_path_for_terminal
from envctl_engine.runtime.session_management import (
    print_session_list,
    print_attach_command,
    kill_session,
)
from envctl_engine.state import state_to_dict
from envctl_engine.state.models import RunState
from envctl_engine.state.project_runtime import (
    cwd_runtime_warnings,
    dependency_mode_summary,
    project_resolution_event_payload,
    resolve_requested_project_state,
)
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.runtime.endpoints_command_support import run_endpoints_command
from envctl_engine.runtime.startup_inspection_support import (
    additional_service_contexts as _additional_service_contexts_impl,
    additional_service_enabled_for_context as _additional_service_enabled_for_context_impl,
    additional_service_urls as _additional_service_urls_impl,
    additional_service_warnings as _additional_service_warnings_impl,
    build_startup_explanation_payload as _build_startup_explanation_payload_impl,
    prediction_payloads as _prediction_payloads_impl,
    print_preflight as _print_preflight_impl,
    print_startup_explanation as _print_startup_explanation_impl,
    render_additional_service_template as _render_additional_service_template_impl,
    startup_route_for_explanation as _startup_route_for_explanation_impl,
    startup_services_payload as _startup_services_payload_impl,
)


def dispatch_direct_inspection(runtime: Any, route: Route) -> int:
    command = str(getattr(route, "command", "")).strip()
    if command == "list-commands":
        commands = list_supported_commands()
        return _print_list_commands(commands, json_output=bool(getattr(route, "flags", {}).get("json")))
    if command in {"list-targets", "list-trees"}:
        return _print_targets(runtime, route, trees_only=(command == "list-trees"))
    if command == "show-config":
        return _print_config(runtime, json_output=bool(getattr(route, "flags", {}).get("json")))
    if command == "show-state":
        return _print_state(runtime, route, json_output=bool(getattr(route, "flags", {}).get("json")))
    if command == "endpoints":
        return run_endpoints_command(runtime, route)
    if command == "explain-startup":
        return _print_startup_explanation(runtime, route, json_output=bool(getattr(route, "flags", {}).get("json")))
    if command == "preflight":
        return _print_preflight(runtime, route, json_output=bool(getattr(route, "flags", {}).get("json")))
    if command == "session":
        return _dispatch_session(runtime, route)
    raise RuntimeError(f"Unsupported direct inspection command: {command}")


def _print_list_commands(commands: list[str], *, json_output: bool) -> int:
    if json_output:
        print(json.dumps({"commands": list(commands)}, indent=2, sort_keys=True))
        return 0
    for cmd in commands:
        print(cmd)
    return 0


def _print_targets(runtime: Any, route: Route, *, trees_only: bool) -> int:
    mode = "trees" if trees_only else str(getattr(route, "mode", "main"))
    projects = runtime._discover_projects(mode=mode)
    if not bool(getattr(route, "flags", {}).get("json")):
        for project in projects:
            print(project.name)
        return 0

    preselected: set[str] = set()
    state_present: set[str] = set()
    services_running: set[str] = set()
    if mode == "trees":
        startup = getattr(runtime, "startup_orchestrator", None)
        if startup is not None:
            preselected = set(_tree_preselected_projects_from_state_impl(runtime=runtime, project_contexts=projects))
        state = _try_load_existing_state(runtime, mode="trees", strict_mode_match=True)
        if state is not None:
            state_present = set(_state_project_names_impl(runtime=runtime, state=state))
            services_running = _running_tree_project_names(runtime=runtime, state=state)

    payload = {
        "mode": mode,
        "count": len(projects),
        "projects": _parallel_project_payloads(
            projects,
            lambda project: {
                "name": project.name,
                "root": str(getattr(project, "root", "")),
                "ports": {name: int(plan.final) for name, plan in getattr(project, "ports", {}).items()},
                "selected": project.name in preselected,
                "preselected": project.name in preselected,
                "state_present": project.name in state_present,
                "services_running": project.name in services_running,
                "running": project.name in services_running,
            },
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def _parallel_project_payloads(projects: list[object], fn) -> list[dict[str, object]]:
    if len(projects) <= 1:
        return [fn(project) for project in projects]
    results: list[dict[str, object] | None] = [None] * len(projects)
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(projects), 8)) as executor:
        future_map = {executor.submit(fn, project): index for index, project in enumerate(projects)}
        for future in concurrent.futures.as_completed(future_map):
            results[future_map[future]] = future.result()
    return [result for result in results if isinstance(result, dict)]


def _running_tree_project_names(*, runtime: Any, state: RunState) -> set[str]:
    running: set[str] = set()
    services = getattr(state, "services", {})
    if not isinstance(services, dict):
        return running
    for service_name, record in services.items():
        project_name = runtime._project_name_from_service(str(service_name))
        normalized = str(project_name).strip()
        if not normalized:
            continue
        status = str(getattr(record, "status", "") or "").strip().lower()
        if status not in {"running", "healthy"}:
            continue
        running.add(normalized)
    return running


def _print_config(runtime: Any, *, json_output: bool) -> int:
    local_state = discover_local_config_state(runtime.config.base_dir, runtime.env.get("ENVCTL_CONFIG_FILE"))
    values = managed_values_from_local_state(local_state)
    _apply_runtime_effective_config_values(values, runtime.config)
    payload: dict[str, Any] = {
        "base_dir": str(runtime.config.base_dir),
        "execution_root": str(runtime.config.execution_root),
        "config_file": str(local_state.config_file_path),
        "config_exists": local_state.config_file_exists,
        "config_source": local_state.config_source,
        "legacy_source_path": str(local_state.legacy_source_path)
        if local_state.legacy_source_path is not None
        else None,
        "effective": managed_values_to_payload(values),
        "dependency_env_section_present": local_state.dependency_env_section_present,
        "dependency_env_templates": [
            {
                "name": entry.name,
                "template": entry.template,
                "line_number": entry.line_number,
            }
            for entry in local_state.dependency_env_templates
        ],
        "backend_dependency_env_section_present": local_state.backend_dependency_env_section_present,
        "backend_dependency_env_templates": [
            {
                "name": entry.name,
                "template": entry.template,
                "line_number": entry.line_number,
            }
            for entry in local_state.backend_dependency_env_templates
        ],
        "frontend_dependency_env_section_present": local_state.frontend_dependency_env_section_present,
        "frontend_dependency_env_projection_active": bool(
            local_state.dependency_env_section_present
            or local_state.frontend_dependency_env_section_present
            or local_state.main_frontend_dependency_env_section_present
            or local_state.trees_frontend_dependency_env_section_present
            or bool(local_state.service_dependency_env_section_present or {})
            or bool(local_state.mode_service_dependency_env_section_present or {})
        ),
        "frontend_dependency_env_templates": [
            {
                "name": entry.name,
                "template": entry.template,
                "line_number": entry.line_number,
            }
            for entry in local_state.frontend_dependency_env_templates
        ],
        "main_backend_dependency_env_section_present": local_state.main_backend_dependency_env_section_present,
        "main_backend_dependency_env_templates": _template_entries(local_state.main_backend_dependency_env_templates),
        "main_frontend_dependency_env_section_present": local_state.main_frontend_dependency_env_section_present,
        "main_frontend_dependency_env_templates": _template_entries(local_state.main_frontend_dependency_env_templates),
        "trees_backend_dependency_env_section_present": local_state.trees_backend_dependency_env_section_present,
        "trees_backend_dependency_env_templates": _template_entries(local_state.trees_backend_dependency_env_templates),
        "trees_frontend_dependency_env_section_present": local_state.trees_frontend_dependency_env_section_present,
        "trees_frontend_dependency_env_templates": _template_entries(
            local_state.trees_frontend_dependency_env_templates
        ),
        "additional_services": [
            {
                "name": service.name,
                "env_suffix": service.env_suffix,
                "enabled_main": service.enabled_main,
                "enabled_trees": service.enabled_trees,
                "dir": service.dir_name,
                "start_cmd": service.start_cmd,
                "test_cmd": service.test_cmd,
                "port_base": service.port_base,
                "expect_listener": service.expect_listener,
                "health_url": service.health_url_template,
                "public_url": service.public_url_template,
                "depends_on": list(service.depends_on),
                "start_order": service.start_order,
                "critical": service.critical,
            }
            for service in getattr(runtime.config, "additional_services", ())
        ],
        "additional_service_errors": list(getattr(runtime.config, "additional_service_errors", ())),
        "service_dependency_env_section_present": dict(local_state.service_dependency_env_section_present or {}),
        "service_dependency_env_templates": {
            name: _template_entries(entries)
            for name, entries in (local_state.service_dependency_env_templates or {}).items()
        },
        "mode_service_dependency_env_section_present": {
            f"{mode}:{service}": present
            for (mode, service), present in (local_state.mode_service_dependency_env_section_present or {}).items()
        },
        "mode_service_dependency_env_templates": {
            f"{mode}:{service}": _template_entries(entries)
            for (mode, service), entries in (local_state.mode_service_dependency_env_templates or {}).items()
        },
        "plan_agent": {
            "enabled": runtime.config.plan_agent_terminals_enable,
            "cli": runtime.config.plan_agent_cli,
            "preset": runtime.config.plan_agent_preset,
            "codex_cycles": runtime.config.plan_agent_codex_cycles,
            "codex_goal_enable": runtime.config.plan_agent_codex_goal_enable,
            "browser_e2e": runtime.config.plan_agent_browser_e2e_enable,
            "pr_review_comments": runtime.config.plan_agent_pr_review_comments_enable,
            "shell": runtime.config.plan_agent_shell,
            "require_cmux_context": runtime.config.plan_agent_require_cmux_context,
            "cli_command": runtime.config.plan_agent_cli_cmd or runtime.config.plan_agent_cli,
            "cmux_workspace": runtime.config.plan_agent_cmux_workspace or None,
            "surface_transport": runtime.config.plan_agent_surface_transport,
            "superset_project": runtime.config.plan_agent_superset_project or None,
            "superset_workspace": runtime.config.plan_agent_superset_workspace or None,
            "superset_host": runtime.config.plan_agent_superset_host or None,
            "superset_local": runtime.config.plan_agent_superset_local,
            "superset_open": runtime.config.plan_agent_superset_open,
        },
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    effective = payload["effective"]
    print(f"config_file: {render_path_for_terminal(payload['config_file'], env=getattr(runtime, 'env', {}))}")
    print(f"execution_root: {render_path_for_terminal(payload['execution_root'], env=getattr(runtime, 'env', {}))}")
    print(f"config_exists: {payload['config_exists']}")
    print(f"config_source: {payload['config_source']}")
    print(f"default_mode: {effective['default_mode']}")
    print(f"main_startup_enabled: {effective['profiles']['main']['startup_enabled']}")
    print(f"trees_startup_enabled: {effective['profiles']['trees']['startup_enabled']}")
    print(f"backend_dir: {effective['directories']['backend']}")
    print(f"frontend_dir: {effective['directories']['frontend']}")
    print(f"backend_port_base: {effective['ports']['backend']}")
    print(f"frontend_port_base: {effective['ports']['frontend']}")
    print(f"port_spacing: {effective['ports']['spacing']}")
    if payload["additional_services"]:
        print("additional_services: " + ", ".join(service["name"] for service in payload["additional_services"]))
    preferred_strategy = (
        runtime.env.get("ENVCTL_PORT_PREFERRED_STRATEGY")
        or runtime.config.raw.get("ENVCTL_PORT_PREFERRED_STRATEGY")
        or "project_slot"
    )
    print(f"preferred_port_strategy: {preferred_strategy}")
    print(f"plan_agent_terminals_enabled: {payload['plan_agent']['enabled']}")
    print(f"plan_agent_codex_cycles: {payload['plan_agent']['codex_cycles']}")
    print(f"plan_agent_codex_goal_enable: {payload['plan_agent']['codex_goal_enable']}")
    return 0


def _template_entries(entries: tuple[object, ...]) -> list[dict[str, object]]:
    return [
        {
            "name": getattr(entry, "name", ""),
            "template": getattr(entry, "template", ""),
            "line_number": getattr(entry, "line_number", 0),
        }
        for entry in entries
    ]


def _apply_runtime_effective_config_values(values: Any, config: Any) -> None:
    values.default_mode = config.default_mode
    values.backend_dir_name = config.backend_dir_name
    values.frontend_dir_name = config.frontend_dir_name
    values.backend_start_cmd = config.backend_start_cmd
    values.frontend_start_cmd = config.frontend_start_cmd
    values.backend_test_cmd = config.backend_test_cmd
    values.frontend_test_cmd = config.frontend_test_cmd
    values.action_test_cmd = config.action_test_cmd
    values.frontend_test_path = config.frontend_test_path
    values.port_defaults = config.port_defaults
    values.main_profile = config.main_profile
    values.trees_profile = config.trees_profile
    values.main_backend_expect_listener = config.main_backend_expect_listener
    values.trees_backend_expect_listener = config.trees_backend_expect_listener


def _print_state(runtime: Any, route: Route, *, json_output: bool) -> int:
    strict = runtime._state_lookup_strict_mode_match(route)
    state = _try_load_existing_state(runtime, mode=route.mode, strict_mode_match=strict)
    if state is None:
        if json_output:
            print(json.dumps({"found": False, "mode": getattr(route, "mode", None)}, indent=2, sort_keys=True))
        else:
            print("No previous state found.")
        return 1
    requested_projects = list(getattr(route, "projects", []) or [])
    if requested_projects:
        resolution = resolve_requested_project_state(
            state,
            requested_projects,
            command="show-state",
            runtime=runtime,
            allow_multi=False,
        )
        if not resolution.ok:
            emitter = getattr(runtime, "_emit", None)
            if callable(emitter):
                emitter(
                    "state.project_resolution.failed",
                    **project_resolution_event_payload(resolution, state, runtime=runtime),
                )
            if json_output:
                print(json.dumps(resolution.payload(), indent=2, sort_keys=True))
            else:
                print(f"Requested project is not running: {resolution.requested_project}")
                print("Active runtime projects: " + (", ".join(resolution.active_projects) or "none"))
            return 1
        emitter = getattr(runtime, "_emit", None)
        if callable(emitter):
            emitter(
                "state.project_resolution.ok",
                **project_resolution_event_payload(resolution, state, runtime=runtime),
            )
        if resolution.state is not None and not bool(getattr(route, "flags", {}).get("all")):
            state = resolution.state

    dependency_summary = dependency_mode_summary(state)
    cwd_project, warnings = cwd_runtime_warnings(
        state,
        runtime=runtime,
        requested_projects=list(getattr(route, "projects", []) or []),
    )
    _emit_cwd_runtime_mismatch_warnings(runtime, command="show-state", state=state, warnings=warnings)
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




def _try_load_existing_state(runtime: Any, *, mode: str | None, strict_mode_match: bool) -> RunState | None:
    loader = getattr(runtime, "_try_load_existing_state", None)
    if not callable(loader):
        return None
    state = loader(mode=mode, strict_mode_match=strict_mode_match)
    return state if isinstance(state, RunState) else None


def _emit_cwd_runtime_mismatch_warnings(
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


def _additional_service_enabled_for_context(runtime: Any, mode: str, service: object, context: object) -> bool:
    return _additional_service_enabled_for_context_impl(runtime, mode, service, context)


def _additional_service_contexts(runtime: Any, mode: str, contexts: list[object], service: object) -> list[object]:
    return _additional_service_contexts_impl(runtime, mode, contexts, service)


def _render_additional_service_template(template: str, values: dict[str, str]) -> str:
    return _render_additional_service_template_impl(template, values)


def _additional_service_urls(runtime: Any, mode: str, contexts: list[object]) -> dict[str, dict[str, object]]:
    return _additional_service_urls_impl(runtime, mode, contexts)


def _additional_service_warnings(runtime: Any, mode: str, contexts: list[object]) -> list[dict[str, object]]:
    return _additional_service_warnings_impl(runtime, mode, contexts)


def _startup_services_payload(runtime: Any, mode: str, contexts: list[object]) -> dict[str, bool]:
    return _startup_services_payload_impl(runtime, mode, contexts)


def _prediction_payloads(
    runtime: Any,
    predictions: list[PlanProjectPrediction],
) -> tuple[list[dict[str, object]], list[object]]:
    return _prediction_payloads_impl(runtime, predictions)


def _build_startup_explanation_payload(runtime: Any, route: object) -> dict[str, object]:
    return _build_startup_explanation_payload_impl(runtime, route)


def _print_startup_explanation(runtime: Any, route: object, *, json_output: bool) -> int:
    return _print_startup_explanation_impl(runtime, route, json_output=json_output)


def _print_preflight(runtime: Any, route: object, *, json_output: bool) -> int:
    return _print_preflight_impl(runtime, route, json_output=json_output)


def _startup_route_for_explanation(runtime: Any, route: object) -> object:
    return _startup_route_for_explanation_impl(runtime, route)


def _dispatch_session(runtime: Any, route: object) -> int:
    action = str(getattr(route, "flags", {}).get("session_action", "") or "").strip().lower()
    session_id = str(getattr(route, "flags", {}).get("session_id_override", "") or "").strip()
    runtime_root = getattr(runtime, "runtime_root", None)
    if runtime_root is None:
        print("Could not determine runtime root.", file=sys.stderr)
        return 1

    if not action and not session_id:
        print_session_list(Path(runtime_root))
        return 0

    if action == "list":
        print_session_list(Path(runtime_root))
        return 0
    if action == "attach":
        if session_id:
            ok = print_attach_command(session_id)
            return 0 if ok else 1
        print("Usage: envctl --session --session-action=attach --session-id-override <name>", file=sys.stderr)
        return 1
    if action == "kill":
        if session_id:
            ok = kill_session(session_id)
            return 0 if ok else 1
        print("Usage: envctl --session --session-action=kill --session-id-override <name>", file=sys.stderr)
        return 1

    print(f"Unknown session action: {action}", file=sys.stderr)
    return 1
