from __future__ import annotations

import concurrent.futures
import json
from typing import Any

from envctl_engine.config import discover_local_config_state
from envctl_engine.config.persistence import managed_values_from_local_state, managed_values_to_payload
from envctl_engine.planning import (
    filter_projects_for_plan,
    list_planning_files,
    resolve_planning_files,
    select_projects_for_plan_files,
)
from envctl_engine.planning.plan_agent_launch_support import inspect_plan_agent_launch
from envctl_engine.runtime.command_router import list_supported_commands, parse_route
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
from envctl_engine.state import state_to_dict


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
    if command == "explain-startup":
        return _print_startup_explanation(runtime, route, json_output=bool(getattr(route, "flags", {}).get("json")))
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
    running: set[str] = set()
    if mode == "trees":
        startup = getattr(runtime, "startup_orchestrator", None)
        if startup is not None:
            preselected = set(
                _tree_preselected_projects_from_state_impl(startup, runtime=runtime, project_contexts=projects)
            )
        state = runtime._try_load_existing_state(mode="trees", strict_mode_match=True)
        if state is not None:
            running = set(_state_project_names_impl(runtime=runtime, state=state))

    payload = {
        "mode": mode,
        "count": len(projects),
        "projects": _parallel_project_payloads(
            projects,
            lambda project: {
                "name": project.name,
                "root": str(getattr(project, "root", "")),
                "ports": {name: int(plan.final) for name, plan in getattr(project, "ports", {}).items()},
                "preselected": project.name in preselected,
                "running": project.name in running,
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


def _print_config(runtime: Any, *, json_output: bool) -> int:
    local_state = discover_local_config_state(runtime.config.base_dir, runtime.env.get("ENVCTL_CONFIG_FILE"))
    values = managed_values_from_local_state(local_state)
    payload = {
        "base_dir": str(runtime.config.base_dir),
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
        "frontend_dependency_env_templates": [
            {
                "name": entry.name,
                "template": entry.template,
                "line_number": entry.line_number,
            }
            for entry in local_state.frontend_dependency_env_templates
        ],
        "plan_agent": {
            "enabled": runtime.config.plan_agent_terminals_enable,
            "cli": runtime.config.plan_agent_cli,
            "preset": runtime.config.plan_agent_preset,
            "codex_cycles": runtime.config.plan_agent_codex_cycles,
            "shell": runtime.config.plan_agent_shell,
            "require_cmux_context": runtime.config.plan_agent_require_cmux_context,
            "cli_command": runtime.config.plan_agent_cli_cmd or runtime.config.plan_agent_cli,
            "cmux_workspace": runtime.config.plan_agent_cmux_workspace or None,
        },
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    effective = payload["effective"]
    print(f"config_file: {payload['config_file']}")
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
    preferred_strategy = (
        runtime.env.get("ENVCTL_PORT_PREFERRED_STRATEGY")
        or runtime.config.raw.get("ENVCTL_PORT_PREFERRED_STRATEGY")
        or "project_slot"
    )
    print(f"preferred_port_strategy: {preferred_strategy}")
    print(f"plan_agent_terminals_enabled: {payload['plan_agent']['enabled']}")
    print(f"plan_agent_codex_cycles: {payload['plan_agent']['codex_cycles']}")
    return 0


def _print_state(runtime: Any, route: object, *, json_output: bool) -> int:
    strict = runtime._state_lookup_strict_mode_match(route)
    state = runtime._try_load_existing_state(mode=getattr(route, "mode", None), strict_mode_match=strict)
    if state is None:
        if json_output:
            print(json.dumps({"found": False, "mode": getattr(route, "mode", None)}, indent=2, sort_keys=True))
        else:
            print("No previous state found.")
        return 1

    payload = {
        "found": True,
        "runtime_root": str(runtime.runtime_root),
        "run_state_path": str(runtime._run_state_path()),
        "state": state_to_dict(state),
    }
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    state_payload = payload["state"]
    print(f"run_id: {state_payload['run_id']}")
    print(f"mode: {state_payload['mode']}")
    print(f"services: {len(state_payload['services'])}")
    print(f"requirements: {len(state_payload['requirements'])}")
    print("run_state_path:")
    print(str(payload["run_state_path"]))
    return 0


def _print_startup_explanation(runtime: Any, route: object, *, json_output: bool) -> int:
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
                    )
                    filtered = select_projects_for_plan_files(
                        projects=[(project.name, project.root) for project in projects],
                        plan_counts=plan_counts,
                    )
                    selected_names = {name for name, _ in filtered}
                    selection_info.update(
                        {
                            "required": False,
                            "reason": "explicit_plan_selectors",
                            "selected_projects": [
                                project.name for project in projects if project.name in selected_names
                            ],
                            "planning_files": list(plan_counts.keys()),
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
    selected_contexts = [project for project in projects if project.name in set(selection_info["selected_projects"])]
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
            "will_resume": run_reuse_decision.decision_kind in {"resume_exact", "resume_subset"},
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
            "run_id": run_reuse_decision.candidate_state.run_id if run_reuse_decision.candidate_state is not None else None,
            "will_reuse_run": run_reuse_decision.will_reuse_run,
            "will_resume_services": run_reuse_decision.will_resume_services,
            "selected_projects": run_reuse_decision.selected_projects,
            "state_projects": run_reuse_decision.state_projects,
            "weak_identity": run_reuse_decision.weak_identity,
            "mismatch_details": run_reuse_decision.mismatch_details,
        },
        "startup_enabled": startup_enabled,
        "services": {
            "backend": runtime.config.service_enabled_for_mode(runtime_mode, "backend"),
            "frontend": runtime.config.service_enabled_for_mode(runtime_mode, "frontend"),
        },
        "dependencies": enabled_dependencies,
        "parallel_trees": {"enabled": parallel_trees_enabled, "workers": parallel_trees_workers},
        "plan_agent_launch": inspect_plan_agent_launch(runtime, route=startup_route),
    }
    if not startup_enabled:
        payload["reason"] = "config_startup_disabled"
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
        f"{payload['run_reuse']['will_reuse_run']} ({payload['run_reuse']['decision_kind']}: {payload['run_reuse']['reason']})"
    )
    deps = ", ".join(enabled_dependencies) or "none"
    print(f"dependencies: {deps}")
    if payload.get("reason"):
        print(f"reason: {payload['reason']}")
    if selection_info.get("message"):
        print(str(selection_info["message"]))
    return 0


def _startup_route_for_explanation(runtime: Any, route: object) -> object:
    raw_args = [
        str(token)
        for token in list(getattr(route, "raw_args", []) or [])
        if str(token).strip() not in {"--explain-startup", "explain-startup"}
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
