from __future__ import annotations

import json
import shlex
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from envctl_engine.planning import (
    PlanProjectPrediction,
    filter_projects_for_plan,
    list_planning_files,
    predict_plan_projects,
    resolve_planning_files,
)
from envctl_engine.planning.plan_agent.launch import inspect_plan_agent_launch
from envctl_engine.runtime.browser_diagnostics import build_startup_env_projection
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime_startup_support import (
    auto_resume_start_enabled,
    evaluate_run_reuse,
    effective_start_mode,
    tree_parallel_startup_config,
)
from envctl_engine.startup.startup_selection_support import (
    _tree_preselected_projects_from_state as _tree_preselected_projects_from_state_impl,
)
from envctl_engine.startup.run_reuse_support import RunReuseDecision


@dataclass(slots=True)
class StartupInspectionBuilder:
    runtime: Any
    route: Any
    startup_route: Any = field(init=False)
    runtime_mode: str = field(init=False)
    batch: bool = field(init=False)
    can_tty: bool = field(init=False)
    projects: list[Any] = field(init=False)
    predicted_contexts: list[Any] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        self.startup_route = startup_route_for_explanation(self.runtime, self.route)
        self.runtime_mode = effective_start_mode(self.runtime, self.route)
        self.batch = self.runtime._batch_mode_requested(self.startup_route)
        self.can_tty = self.runtime._can_interactive_tty()
        self.projects = self.runtime._discover_projects(mode=self.runtime_mode)

    def build(self) -> dict[str, Any]:
        selection_info = self._selection_info()
        selected_projects = cast(list[str], selection_info.get("selected_projects", []))
        selected_project_count = len(selected_projects)
        selected_names = set(selected_projects)
        selected_contexts = self.predicted_contexts or [
            project for project in self.projects if project.name in selected_names
        ]
        run_reuse_decision = cast(
            RunReuseDecision,
            evaluate_run_reuse(
                self.runtime,
                runtime_mode=self.runtime_mode,
                route=self.startup_route,
                contexts=selected_contexts,
            ),
        )
        profile = self.runtime.config.profile_for_mode(self.runtime_mode)
        startup_enabled = self.runtime.config.startup_enabled_for_mode(self.runtime_mode)
        enabled_dependencies = (
            [
                dependency_id
                for dependency_id in sorted(profile.dependencies)
                if profile.dependency_enabled(dependency_id)
            ]
            if startup_enabled
            else []
        )
        parallel_trees_enabled, parallel_trees_workers = tree_parallel_startup_config(
            self.runtime,
            mode=self.runtime_mode,
            route=self.route,
            project_count=max(selected_project_count, len(self.projects)),
        )
        payload = {
            "command": getattr(self.startup_route, "command", "start"),
            "mode": self.runtime_mode,
            "headless": self.batch or not self.can_tty,
            "interactive_tty": self.can_tty,
            "selection": selection_info,
            "auto_resume": self._auto_resume_payload(run_reuse_decision),
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
            "services": startup_services_payload(self.runtime, self.runtime_mode, selected_contexts),
            "additional_service_urls": additional_service_urls(self.runtime, self.runtime_mode, selected_contexts),
            "warnings": additional_service_warnings(self.runtime, self.runtime_mode, selected_contexts),
            "dependencies": enabled_dependencies,
            "parallel_trees": {"enabled": parallel_trees_enabled, "workers": parallel_trees_workers},
            "plan_agent_launch": inspect_plan_agent_launch(self.runtime, route=self.startup_route),
        }
        payload["env_projection"] = build_startup_env_projection(
            self.runtime,
            self.startup_route,
            mode=self.runtime_mode,
            contexts=selected_contexts,
        )
        if not startup_enabled:
            payload["reason"] = "config_startup_disabled"
        return payload

    def _selection_info(self) -> dict[str, Any]:
        selection_info: dict[str, Any] = {
            "required": False,
            "reason": None,
            "selected_projects": [project.name for project in self.projects],
            "discovered_projects": [project.name for project in self.projects],
            "preselected_projects": [],
        }
        if getattr(self.startup_route, "command", "") == "plan":
            self._apply_plan_selection(selection_info)
        elif (
            self.runtime_mode == "trees"
            and not getattr(self.route, "projects", None)
            and not getattr(self.startup_route, "passthrough_args", None)
        ):
            self._apply_tree_selection_requirement(selection_info)
        elif getattr(self.startup_route, "projects", None):
            allowed = {project.lower() for project in self.startup_route.projects}
            selection_info.update(
                {
                    "reason": "explicit_project_filters",
                    "selected_projects": [project.name for project in self.projects if project.name.lower() in allowed],
                }
            )
        return selection_info

    def _apply_plan_selection(self, selection_info: dict[str, Any]) -> None:
        planning_files = list_planning_files(self.runtime.config.planning_dir)
        selection_raw = ",".join(getattr(self.startup_route, "passthrough_args", [])).strip()
        if selection_raw:
            if planning_files:
                self._apply_plan_file_selection(selection_info, selection_raw, planning_files)
            else:
                filtered = filter_projects_for_plan(
                    [(project.name, project.root) for project in self.projects],
                    getattr(self.startup_route, "passthrough_args", []),
                    strict_no_match=self.runtime.config.plan_strict_selection,
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
        elif not (self.can_tty and not self.batch):
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

    def _apply_plan_file_selection(
        self,
        selection_info: dict[str, Any],
        selection_raw: str,
        planning_files: list[str],
    ) -> None:
        try:
            plan_counts = resolve_planning_files(
                selection_raw=selection_raw,
                planning_files=planning_files,
                base_dir=self.runtime.config.base_dir,
                planning_dir=self.runtime.config.planning_dir,
                requested_cli=str(
                    self.runtime.env.get("ENVCTL_PLAN_AGENT_CLI")
                    or self.runtime.config.raw.get("ENVCTL_PLAN_AGENT_CLI")
                    or ""
                ),
            )
            predictions = predict_plan_projects(
                projects=[(project.name, project.root) for project in self.projects],
                plan_counts=plan_counts,
                base_dir=self.runtime.config.base_dir,
                trees_dir_name=self.runtime.config.trees_dir_name,
            )
            predicted_payloads, self.predicted_contexts = prediction_payloads(self.runtime, predictions)
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

    def _apply_tree_selection_requirement(self, selection_info: dict[str, Any]) -> None:
        preselected = _tree_preselected_projects_from_state_impl(runtime=self.runtime, project_contexts=self.projects)
        selection_info.update({"required": True, "preselected_projects": preselected})
        if self.batch or not self.can_tty:
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

    def _auto_resume_payload(self, run_reuse_decision: RunReuseDecision) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "eligible": auto_resume_start_enabled(self.startup_route),
            "existing_state_found": run_reuse_decision.candidate_state is not None,
            "exact_match": run_reuse_decision.decision_kind in {"resume_exact", "resume_dashboard_exact"},
            "subset_match": run_reuse_decision.decision_kind == "resume_subset",
            "will_resume": run_reuse_decision.decision_kind in {"resume_exact", "resume_subset", "reuse_expand"},
            "reason": run_reuse_decision.reason,
        }
        if run_reuse_decision.candidate_state is not None:
            payload["run_id"] = run_reuse_decision.candidate_state.run_id
        return payload


def prediction_payloads(
    runtime: Any,
    predictions: list[PlanProjectPrediction],
) -> tuple[list[dict[str, Any]], list[object]]:
    if not predictions:
        return [], []
    raw_projects = [(prediction.name, prediction.root) for prediction in predictions]
    contexts = runtime._contexts_from_raw_projects(raw_projects)
    by_name = {str(getattr(context, "name", "")): context for context in contexts}
    payloads: list[dict[str, Any]] = []
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


def additional_service_enabled_for_context(runtime: Any, mode: str, service: object, context: object) -> bool:
    root = getattr(context, "root", None)
    enabled_for_project = getattr(service, "enabled_for_project_root", None)
    if callable(enabled_for_project):
        return bool(enabled_for_project(mode, root))
    enabled_for_mode = getattr(service, "enabled_for_mode", None)
    if callable(enabled_for_mode):
        return bool(enabled_for_mode(mode))
    return False


def additional_service_contexts(runtime: Any, mode: str, contexts: list[object], service: object) -> list[object]:
    return [context for context in contexts if additional_service_enabled_for_context(runtime, mode, service, context)]


def render_additional_service_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace(f"${{{key}}}", value)
    return rendered


def additional_service_urls(runtime: Any, mode: str, contexts: list[object]) -> dict[str, dict[str, Any]]:
    host = str(getattr(runtime.config, "raw", {}).get("ENVCTL_PUBLIC_HOST") or "localhost").strip() or "localhost"
    urls: dict[str, dict[str, Any]] = {}
    for service in getattr(runtime.config, "additional_services", ()):
        enabled_contexts = additional_service_contexts(runtime, mode, contexts, service)
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
        public_url = render_additional_service_template(public_url, variables)
        variables[f"ENVCTL_SOURCE_SERVICE_{env_suffix}_PUBLIC_URL"] = public_url
        health_template = str(getattr(service, "health_url_template", "") or "").strip()
        health_url = render_additional_service_template(health_template, variables) if health_template else None
        urls[service.name] = {"port": port, "public_url": public_url, "health_url": health_url}
    return urls


def additional_service_warnings(runtime: Any, mode: str, contexts: list[object]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for service in getattr(runtime.config, "additional_services", ()):
        for context in additional_service_contexts(runtime, mode, contexts, service):
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


def startup_services_payload(runtime: Any, mode: str, contexts: list[object]) -> dict[str, bool]:
    services = {
        "backend": runtime.config.service_enabled_for_mode(mode, "backend"),
        "frontend": runtime.config.service_enabled_for_mode(mode, "frontend"),
    }
    for service in getattr(runtime.config, "additional_services", ()):
        services[service.name] = bool(additional_service_contexts(runtime, mode, contexts, service))
    return services


def build_startup_explanation_payload(runtime: Any, route: object) -> dict[str, Any]:
    return StartupInspectionBuilder(runtime, route).build()


def build_preflight_payload(runtime: Any, route: object) -> dict[str, Any]:
    payload = build_startup_explanation_payload(runtime, route)
    selection = payload.get("selection")
    selection_required = bool(selection.get("required", False)) if isinstance(selection, dict) else False
    return {
        "contract_version": "envctl.preflight.v1",
        "surface": "preflight",
        "mode": payload["mode"],
        "command": payload["command"],
        "startup_enabled": payload["startup_enabled"],
        "selection_required": selection_required,
        "startup": payload,
    }


def print_startup_explanation(runtime: Any, route: object, *, json_output: bool) -> int:
    payload = build_startup_explanation_payload(runtime, route)
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


def print_preflight(runtime: Any, route: object, *, json_output: bool) -> int:
    if json_output:
        print(json.dumps(build_preflight_payload(runtime, route), indent=2, sort_keys=True))
        return 0

    print("surface: preflight")
    return print_startup_explanation(runtime, route, json_output=False)


def startup_route_for_explanation(runtime: Any, route: object) -> object:
    raw_args = [
        str(token)
        for token in list(getattr(route, "raw_args", []) or [])
        if str(token).strip() not in {"--explain-startup", "explain-startup", "--preflight", "preflight"}
    ]
    env = {**getattr(getattr(runtime, "config", None), "raw", {}), **getattr(runtime, "env", {})}
    try:
        return parse_route(raw_args or ["start"], env=env)
    except Exception:
        return SimpleNamespace(
            command="start",
            mode=getattr(route, "mode", "main"),
            raw_args=getattr(route, "raw_args", []),
            passthrough_args=getattr(route, "passthrough_args", []),
            projects=getattr(route, "projects", []),
            flags=dict(getattr(route, "flags", {})),
        )
