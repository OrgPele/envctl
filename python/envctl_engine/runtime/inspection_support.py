from __future__ import annotations

import concurrent.futures
import json
import shlex
import sys
from pathlib import Path
from typing import Any

from envctl_engine.config import discover_local_config_state
from envctl_engine.config.persistence import managed_values_from_local_state, managed_values_to_payload
from envctl_engine.planning import (
    PlanProjectPrediction,
    filter_projects_for_plan,
    list_planning_files,
    predict_plan_projects,
    resolve_planning_files,
)
from envctl_engine.planning.plan_agent.launch import inspect_plan_agent_launch
from envctl_engine.runtime.command_router import list_supported_commands, parse_route
from envctl_engine.runtime.browser_diagnostics import build_startup_env_projection
from envctl_engine.runtime.engine_runtime_startup_support import (
    auto_resume_start_enabled,
    evaluate_run_reuse,
    effective_start_mode,
    tree_parallel_startup_config,
)
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
from envctl_engine.state.project_runtime import (
    cwd_runtime_warnings,
    dependency_mode_summary,
    project_resolution_event_payload,
    resolve_requested_project_state,
)
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.runtime.endpoints_command_support import run_endpoints_command


def dispatch_direct_inspection(runtime: Any, route: object) -> int:
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


def _print_targets(runtime: Any, route: object, *, trees_only: bool) -> int:
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
            preselected = set(
                _tree_preselected_projects_from_state_impl(startup, runtime=runtime, project_contexts=projects)
            )
        state = runtime._try_load_existing_state(mode="trees", strict_mode_match=True)
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


def _running_tree_project_names(*, runtime: Any, state: Any) -> set[str]:
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


def _prediction_payloads(
    runtime: Any,
    predictions: list[PlanProjectPrediction],
) -> tuple[list[dict[str, object]], list[object]]:
    if not predictions:
        return [], []
    raw_projects = [(prediction.name, prediction.root) for prediction in predictions]
    contexts = runtime._contexts_from_raw_projects(raw_projects)
    by_name = {str(getattr(context, "name", "")): context for context in contexts}
    payloads: list[dict[str, object]] = []
    ordered_contexts: list[object] = []
    for prediction in predictions:
        context = by_name.get(prediction.name)
        if context is None:
            continue
        ordered_contexts.append(context)
        payloads.append(
            {
                "name": prediction.name,
                "root": str(prediction.root),
                "plan_file": prediction.plan_file,
                "action": prediction.action,
                "exists": prediction.action == "reuse",
                "ports": {name: int(plan.final) for name, plan in getattr(context, "ports", {}).items()},
            }
        )
    return payloads, ordered_contexts


def _print_config(runtime: Any, *, json_output: bool) -> int:
    local_state = discover_local_config_state(runtime.config.base_dir, runtime.env.get("ENVCTL_CONFIG_FILE"))
    values = managed_values_from_local_state(local_state)
    _apply_runtime_effective_config_values(values, runtime.config)
    payload = {
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
            "surface_transport": runtime.config.plan_agent_surface_transport,
            "cmux_workspace": runtime.config.plan_agent_cmux_workspace or None,
            "superset_workspace": runtime.config.plan_agent_superset_workspace or None,
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


def _print_state(runtime: Any, route: object, *, json_output: bool) -> int:
    strict = runtime._state_lookup_strict_mode_match(route)
    state = runtime._try_load_existing_state(mode=getattr(route, "mode", None), strict_mode_match=strict)
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
    payload = {
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




def _emit_cwd_runtime_mismatch_warnings(
    runtime: Any,
    *,
    command: str,
    state: Any,
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
    root = getattr(context, "root", None)
    enabled_for_project = getattr(service, "enabled_for_project_root", None)
    if callable(enabled_for_project):
        return bool(enabled_for_project(mode, root))
    enabled_for_mode = getattr(service, "enabled_for_mode", None)
    if callable(enabled_for_mode):
        return bool(enabled_for_mode(mode))
    return False


def _additional_service_contexts(runtime: Any, mode: str, contexts: list[object], service: object) -> list[object]:
    return [context for context in contexts if _additional_service_enabled_for_context(runtime, mode, service, context)]


def _render_additional_service_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"${{{key}}}", value)
    return rendered


def _additional_service_urls(runtime: Any, mode: str, contexts: list[object]) -> dict[str, dict[str, object]]:
    host = str(getattr(runtime.config, "raw", {}).get("ENVCTL_PUBLIC_HOST") or "localhost").strip() or "localhost"
    urls: dict[str, dict[str, object]] = {}
    for service in getattr(runtime.config, "additional_services", ()):
        enabled_contexts = _additional_service_contexts(runtime, mode, contexts, service)
        if not enabled_contexts:
            continue
        context = enabled_contexts[0]
        ports = getattr(context, "ports", {})
        plan = ports.get(service.name) if isinstance(ports, dict) else None
        port = int(getattr(plan, "final", 0) or 0)
        if port <= 0 or not bool(getattr(service, "expect_listener", True)):
            continue
        env_suffix = str(getattr(service, "env_suffix", "") or service.name.upper().replace("-", "_"))
        public_template = str(getattr(service, "public_url_template", "") or "").strip()
        public_url = public_template or f"http://{host}:{port}"
        variables = {
            f"ENVCTL_SOURCE_SERVICE_{env_suffix}_HOST": host,
            f"ENVCTL_SOURCE_SERVICE_{env_suffix}_PORT": str(port),
            f"ENVCTL_SOURCE_SERVICE_{env_suffix}_URL": f"http://{host}:{port}",
            f"ENVCTL_SOURCE_SERVICE_{env_suffix}_PUBLIC_URL": public_url,
        }
        public_url = _render_additional_service_template(public_url, variables)
        variables[f"ENVCTL_SOURCE_SERVICE_{env_suffix}_PUBLIC_URL"] = public_url
        health_template = str(getattr(service, "health_url_template", "") or "").strip()
        health_url = _render_additional_service_template(health_template, variables) if health_template else None
        urls[service.name] = {"port": port, "public_url": public_url, "health_url": health_url}
    return urls


def _additional_service_warnings(runtime: Any, mode: str, contexts: list[object]) -> list[dict[str, object]]:
    warnings: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for service in getattr(runtime.config, "additional_services", ()):
        for context in _additional_service_contexts(runtime, mode, contexts, service):
            command = str(getattr(service, "start_cmd", "") or "").strip()
            if not command:
                continue
            try:
                parts = shlex.split(command)
            except ValueError:
                continue
            if not parts:
                continue
            executable = parts[0]
            if "/" not in executable and "\\" not in executable:
                continue
            service_dir = (
                Path(getattr(context, "root")) / str(getattr(service, "dir_name", ".") or ".")
            ).resolve(strict=False)
            candidate = Path(executable)
            if not candidate.is_absolute():
                candidate = (service_dir / executable).resolve(strict=False)
            if candidate.exists():
                continue
            key = (str(getattr(context, "name", "")), str(getattr(service, "name", "")), str(candidate))
            if key in seen:
                continue
            seen.add(key)
            warnings.append(
                {
                    "project": str(getattr(context, "name", "")),
                    "service": str(getattr(service, "name", "")),
                    "reason": "missing_command_path",
                    "path": str(candidate),
                    "message": (
                        f"Configured service {getattr(service, 'name', '')!r} command path is missing for "
                        f"{getattr(context, 'name', '')}: {candidate}"
                    ),
                }
            )
    return warnings


def _startup_services_payload(runtime: Any, mode: str, contexts: list[object]) -> dict[str, bool]:
    services = {
        "backend": runtime.config.service_enabled_for_mode(mode, "backend"),
        "frontend": runtime.config.service_enabled_for_mode(mode, "frontend"),
    }
    for service in getattr(runtime.config, "additional_services", ()):
        services[service.name] = bool(_additional_service_contexts(runtime, mode, contexts, service))
    return services


def _build_startup_explanation_payload(runtime: Any, route: object) -> dict[str, object]:
    startup_route = _startup_route_for_explanation(runtime, route)
    runtime_mode = effective_start_mode(runtime, route)
    batch = runtime._batch_mode_requested(startup_route)
    can_tty = runtime._can_interactive_tty()
    projects = runtime._discover_projects(mode=runtime_mode)
    startup = runtime.startup_orchestrator
    selection_info: dict[str, object] = {
        "required": False,
        "reason": None,
        "selected_projects": [project.name for project in projects],
        "discovered_projects": [project.name for project in projects],
        "preselected_projects": [],
    }

    predicted_contexts: list[object] = []
    if getattr(startup_route, "command", "") == "plan":
        planning_files = list_planning_files(runtime.config.planning_dir)
        selection_raw = ",".join(getattr(startup_route, "passthrough_args", [])).strip()
        if selection_raw:
            if planning_files:
                try:
                    plan_counts = resolve_planning_files(
                        selection_raw=selection_raw,
                        planning_files=planning_files,
                        base_dir=runtime.config.base_dir,
                        planning_dir=runtime.config.planning_dir,
                        requested_cli=str(
                            runtime.env.get("ENVCTL_PLAN_AGENT_CLI")
                            or runtime.config.raw.get("ENVCTL_PLAN_AGENT_CLI")
                            or ""
                        ),
                    )
                    predictions = predict_plan_projects(
                        projects=[(project.name, project.root) for project in projects],
                        plan_counts=plan_counts,
                        base_dir=runtime.config.base_dir,
                        trees_dir_name=runtime.config.trees_dir_name,
                    )
                    predicted_payloads, predicted_contexts = _prediction_payloads(runtime, predictions)
                    selection_info.update(
                        {
                            "required": False,
                            "reason": "explicit_plan_selectors",
                            "selected_projects": [payload["name"] for payload in predicted_payloads],
                            "planning_files": list(plan_counts.keys()),
                            "predicted_projects": predicted_payloads,
                        }
                    )
                except ValueError as exc:
                    selection_info.update(
                        {"required": True, "reason": f"invalid_plan_selection: {exc}", "selected_projects": []}
                    )
            else:
                filtered = filter_projects_for_plan(
                    [(project.name, project.root) for project in projects],
                    getattr(startup_route, "passthrough_args", []),
                    strict_no_match=runtime.config.plan_strict_selection,
                )
                selection_info.update(
                    {
                        "required": False,
                        "reason": "explicit_project_filters",
                        "selected_projects": [name for name, _ in filtered],
                    }
                )
        elif not planning_files:
            selection_info.update(
                {
                    "required": True,
                    "reason": "no_planning_files",
                    "message": "No planning files found. Use explicit selectors or use --trees.",
                    "selected_projects": [],
                }
            )
        elif not (can_tty and not batch):
            selection_info.update(
                {
                    "required": True,
                    "reason": "headless_plan_requires_explicit_selection",
                    "message": "Run 'envctl --list-trees --json' and then 'envctl --headless --plan <selector>'.",
                    "selected_projects": [],
                }
            )
        else:
            selection_info.update({"required": True, "reason": "interactive_plan_selector", "selected_projects": []})
    elif (
        runtime_mode == "trees"
        and not getattr(route, "projects", None)
        and not getattr(startup_route, "passthrough_args", None)
    ):
        preselected = _tree_preselected_projects_from_state_impl(startup, runtime=runtime, project_contexts=projects)
        selection_info.update({"required": True, "preselected_projects": preselected})
        if batch or not can_tty:
            selection_info.update(
                {
                    "reason": "headless_tree_start_requires_explicit_selection",
                    "message": (
                        "Run 'envctl --list-trees --json' and retry with '--project <tree>' or '--plan <selector>'."
                    ),
                    "selected_projects": [],
                }
            )
        else:
            selection_info.update({"reason": "interactive_tree_start_selector", "selected_projects": []})
    elif getattr(startup_route, "projects", None):
        allowed = {project.lower() for project in startup_route.projects}
        selection_info.update(
            {
                "reason": "explicit_project_filters",
                "selected_projects": [project.name for project in projects if project.name.lower() in allowed],
            }
        )

    selected_project_count = len(selection_info.get("selected_projects", []))
    auto_resume = {
        "eligible": auto_resume_start_enabled(startup_route),
        "existing_state_found": False,
        "exact_match": False,
        "subset_match": False,
        "will_resume": False,
        "reason": None,
    }
    selected_names = set(selection_info["selected_projects"])
    selected_contexts = predicted_contexts or [
        project for project in projects if project.name in selected_names
    ]
    run_reuse_decision = evaluate_run_reuse(
        runtime,
        runtime_mode=runtime_mode,
        route=startup_route,
        contexts=selected_contexts,
    )
    auto_resume.update(
        {
            "existing_state_found": run_reuse_decision.candidate_state is not None,
            "exact_match": run_reuse_decision.decision_kind in {"resume_exact", "resume_dashboard_exact"},
            "subset_match": run_reuse_decision.decision_kind == "resume_subset",
            "will_resume": run_reuse_decision.decision_kind in {"resume_exact", "resume_subset", "reuse_expand"},
            "reason": run_reuse_decision.reason,
        }
    )
    if run_reuse_decision.candidate_state is not None:
        auto_resume["run_id"] = run_reuse_decision.candidate_state.run_id

    profile = runtime.config.profile_for_mode(runtime_mode)
    startup_enabled = runtime.config.startup_enabled_for_mode(runtime_mode)
    enabled_dependencies = []
    if startup_enabled:
        enabled_dependencies = [
            dependency_id for dependency_id in sorted(profile.dependencies) if profile.dependency_enabled(dependency_id)
        ]
    parallel_trees_enabled, parallel_trees_workers = tree_parallel_startup_config(
        runtime,
        mode=runtime_mode,
        route=route,
        project_count=max(selected_project_count, len(projects)),
    )
    payload = {
        "command": getattr(startup_route, "command", "start"),
        "mode": runtime_mode,
        "headless": batch or not can_tty,
        "interactive_tty": can_tty,
        "selection": selection_info,
        "auto_resume": auto_resume,
        "run_reuse": {
            "decision_kind": run_reuse_decision.decision_kind,
            "reason": run_reuse_decision.reason,
            "run_id": (
                run_reuse_decision.candidate_state.run_id
                if run_reuse_decision.candidate_state is not None
                else None
            ),
            "will_reuse_run": run_reuse_decision.will_reuse_run,
            "will_resume_services": run_reuse_decision.will_resume_services,
            "selected_projects": run_reuse_decision.selected_projects,
            "state_projects": run_reuse_decision.state_projects,
            "weak_identity": run_reuse_decision.weak_identity,
            "mismatch_details": run_reuse_decision.mismatch_details,
        },
        "startup_enabled": startup_enabled,
        "services": _startup_services_payload(runtime, runtime_mode, selected_contexts),
        "additional_service_urls": _additional_service_urls(runtime, runtime_mode, selected_contexts),
        "warnings": _additional_service_warnings(runtime, runtime_mode, selected_contexts),
        "dependencies": enabled_dependencies,
        "parallel_trees": {"enabled": parallel_trees_enabled, "workers": parallel_trees_workers},
        "plan_agent_launch": inspect_plan_agent_launch(runtime, route=startup_route),
    }
    payload["env_projection"] = build_startup_env_projection(
        runtime,
        startup_route,
        mode=runtime_mode,
        contexts=selected_contexts,
    )
    if not startup_enabled:
        payload["reason"] = "config_startup_disabled"
    return payload


def _print_startup_explanation(runtime: Any, route: object, *, json_output: bool) -> int:
    payload = _build_startup_explanation_payload(runtime, route)
    selection_info = payload["selection"]
    auto_resume = payload["auto_resume"]
    enabled_dependencies = payload["dependencies"]
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"command: {payload['command']}")
    print(f"mode: {payload['mode']}")
    print(f"startup_enabled: {payload['startup_enabled']}")
    print(f"headless: {payload['headless']}")
    print(f"selected_projects: {', '.join(selection_info.get('selected_projects', [])) or 'none'}")
    print(f"auto_resume: {auto_resume['will_resume']} ({auto_resume['reason']})")
    print(
        "run_reuse: "
        f"{payload['run_reuse']['will_reuse_run']} ("
        f"{payload['run_reuse']['decision_kind']}: {payload['run_reuse']['reason']})"
    )
    deps = ", ".join(enabled_dependencies) or "none"
    print(f"dependencies: {deps}")
    if payload.get("reason"):
        print(f"reason: {payload['reason']}")
    if selection_info.get("message"):
        print(str(selection_info["message"]))
    return 0


def _print_preflight(runtime: Any, route: object, *, json_output: bool) -> int:
    payload = _build_startup_explanation_payload(runtime, route)
    selection = payload.get("selection")
    selection_required = bool(selection.get("required", False)) if isinstance(selection, dict) else False
    if json_output:
        print(
            json.dumps(
                {
                    "contract_version": "envctl.preflight.v1",
                    "surface": "preflight",
                    "mode": payload["mode"],
                    "command": payload["command"],
                    "startup_enabled": payload["startup_enabled"],
                    "selection_required": selection_required,
                    "startup": payload,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    print("surface: preflight")
    return _print_startup_explanation(runtime, route, json_output=False)


def _startup_route_for_explanation(runtime: Any, route: object) -> object:
    raw_args = [
        str(token)
        for token in list(getattr(route, "raw_args", []) or [])
        if str(token).strip() not in {"--explain-startup", "explain-startup", "--preflight", "preflight"}
    ]
    env = {**getattr(getattr(runtime, "config", None), "raw", {}), **getattr(runtime, "env", {})}
    try:
        return parse_route(raw_args or ["start"], env=env)
    except Exception:
        return type(route)(
            command="start",
            mode=getattr(route, "mode", "main"),
            raw_args=getattr(route, "raw_args", []),
            passthrough_args=getattr(route, "passthrough_args", []),
            projects=getattr(route, "projects", []),
            flags=dict(getattr(route, "flags", {})),
        )


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
