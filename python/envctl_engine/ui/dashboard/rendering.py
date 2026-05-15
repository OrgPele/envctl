from __future__ import annotations

# pyright: reportUnusedFunction=false

import concurrent.futures
from datetime import datetime
import json
import re
import shlex
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Mapping, cast

from envctl_engine.dashboard_metadata import (
    DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY,
    dashboard_configured_missing_services_by_project,
    dashboard_project_configured_services_from_metadata,
    normalize_dashboard_service_types,
)
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.shared.services import service_display_name
from envctl_engine.ui.color_policy import colors_enabled
from envctl_engine.ui.path_links import render_path_for_terminal
from envctl_engine.ui.status_symbols import (
    STATUS_NEUTRAL,
    dependency_status_badge,
    service_status_badge,
)

_DASHBOARD_VISUAL_HOST_ENV = "ENVCTL_UI_VISUAL_HOST"
_DASHBOARD_PUBLIC_HOST_ENV = "ENVCTL_PUBLIC_HOST"


def _print_dashboard_snapshot(self: Any, state: RunState) -> None:
    reconcile_for_snapshot = getattr(self, "_dashboard_reconcile_for_snapshot", None)
    if callable(reconcile_for_snapshot):
        failing_services = list(cast(list[str], reconcile_for_snapshot(state)))
    else:
        failing_services = self._reconcile_state_truth(state)
    self._emit(
        "state.reconcile",
        run_id=state.run_id,
        source="dashboard.snapshot",
        missing_count=len(failing_services),
        missing_services=failing_services,
    )
    visual_host = _dashboard_visual_host(self)
    runtime_map = build_runtime_map(state, host=visual_host)
    projection = runtime_map.get("projection", {})
    if not isinstance(projection, dict):
        projection = {}
    if not projection:
        metadata_roots = state.metadata.get("project_roots")
        if isinstance(metadata_roots, dict):
            projection = {str(project).strip(): {} for project in metadata_roots if str(project).strip()}
    stopped_services = _dashboard_stopped_services_by_project(state)
    project_configured_services = _dashboard_project_configured_services(state)
    configured_missing_services = dashboard_configured_missing_services_by_project(
        configured_services=project_configured_services,
        stopped_services=stopped_services,
        active_service_names=set(state.services),
    )
    if stopped_services or project_configured_services:
        projection = dict(projection)
        for project in stopped_services:
            projection.setdefault(project, {})
        for project in project_configured_services:
            projection.setdefault(project, {})
    terminal_width, _ = self._terminal_size()
    project_name_budget = max(20, terminal_width - 4)
    palette = self._dashboard_palette()
    reset = palette["reset"]
    bold = palette["bold"]
    cyan = palette["cyan"]
    green = palette["green"]
    yellow = palette["yellow"]
    red = palette["red"]
    blue = palette["blue"]
    magenta = palette["magenta"]
    gray = palette["gray"]
    dim = palette["dim"]
    separator = "=" * 56
    runs_disabled_dashboard = _dashboard_runs_disabled(state)
    stopped_service_count = _dashboard_visible_stopped_service_count(
        state,
        stopped_services=stopped_services,
        configured_missing_services=configured_missing_services,
    )
    if configured_missing_services:
        self._emit(
            "dashboard.configured_missing_services",
            run_id=state.run_id,
            services={project: sorted(service_types) for project, service_types in configured_missing_services.items()},
            metadata_key=DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY,
        )
    service_statuses = [
        str(getattr(service, "status", "unknown") or "unknown").strip().lower() for service in state.services.values()
    ]
    total_services = len(service_statuses) + stopped_service_count
    running_services = sum(1 for status in service_statuses if status in {"running", "healthy"})
    issue_services = sum(1 for status in service_statuses if service_status_badge(status).severity == "failure")
    starting_services = sum(1 for status in service_statuses if service_status_badge(status).severity == "warning")

    print(f"{cyan}{separator}{reset}")
    print(f"{bold}{cyan}Development Environment - Interactive Mode{reset}")
    print(f"{cyan}{separator}{reset}")
    current_session_id = getattr(self, "_current_session_id", None)
    session_id = current_session_id() if callable(current_session_id) else None
    session_id_text = str(session_id).strip() if isinstance(session_id, str) else ""
    if not session_id_text:
        session_id_text = "unknown"
    print(f"{dim}run_id: {state.run_id}  session_id: {session_id_text}  mode: {state.mode}{reset}")
    dashboard_banner = state.metadata.get("dashboard_banner")
    if isinstance(dashboard_banner, str) and dashboard_banner.strip():
        print(f"{dim}{dashboard_banner.strip()}{reset}")
    configured_service_types = _dashboard_configured_service_types(state)
    configured_service_total = _dashboard_configured_service_total(
        projection=projection,
        configured_service_types=configured_service_types,
    )
    ordered_projects = sorted(projection)
    project_prs = _dashboard_project_pr_map(self, state=state, projects=ordered_projects)
    shared_dependency_grouping = _dashboard_dependency_scope(state) == "shared"
    if runs_disabled_dashboard and configured_service_total > 0:
        print(f"{bold}{cyan}Configured Services:{reset}")
        print(
            f"{dim}services: {configured_service_total} configured | {running_services} running | "
            f"{configured_service_total - running_services} not running | {issue_services} issues{reset}"
        )
    else:
        print(f"{bold}{cyan}Running Services:{reset}")
        if stopped_service_count:
            print(
                f"{dim}services: {total_services} total | {running_services} running | "
                f"{stopped_service_count} not running | {starting_services} starting/unknown | "
                f"{issue_services} issues{reset}"
            )
        else:
            print(
                f"{dim}services: {total_services} total | {running_services} running | "
                f"{starting_services} starting/unknown | {issue_services} issues{reset}"
            )
    print(f"{cyan}{separator}{reset}")
    project_colors = [blue, magenta, cyan, green, yellow]
    for project_index, project in enumerate(ordered_projects):
        item = projection.get(project, {})
        if not isinstance(item, dict):
            continue
        backend_url = item.get("backend_url")
        frontend_url = item.get("frontend_url")
        backend_service = state.services.get(f"{project} Backend")
        frontend_service = state.services.get(f"{project} Frontend")
        stopped_for_project = stopped_services.get(project, {})
        configured_missing_for_project = configured_missing_services.get(project, set())
        backend_stopped = backend_service is None and (
            "backend" in stopped_for_project or "backend" in configured_missing_for_project
        )
        frontend_stopped = frontend_service is None and (
            "frontend" in stopped_for_project or "frontend" in configured_missing_for_project
        )
        project_display = self._truncate_text(project, project_name_budget)
        project_color = project_colors[project_index % len(project_colors)]
        project_pr = project_prs.get(project)
        if project_pr is not None:
            project_pr_url, project_pr_state = project_pr
            merged_suffix = f" {dim}(merged){reset}" if project_pr_state == "merged" else ""
            print(
                f"  {bold}{project_color}{project_display}{reset} {dim}PR:{reset} "
                f"{gray}{project_pr_url}{reset}{merged_suffix}"
            )
        else:
            print(f"  {bold}{project_color}{project_display}{reset}")
        show_configured_backend = runs_disabled_dashboard and "backend" in configured_service_types
        if backend_service is not None or backend_stopped or show_configured_backend:
            self._print_dashboard_service_row(
                label="Backend",
                service=backend_service,
                url=str(backend_url) if backend_url else None,
                stopped_not_running=backend_stopped,
                configured_not_running=bool(
                    runs_disabled_dashboard and backend_service is None and "backend" in configured_service_types
                ),
                ok_color=green,
                warn_color=yellow,
                bad_color=red,
                label_color=cyan,
                dim=dim,
                reset=reset,
            )
        show_configured_frontend = runs_disabled_dashboard and "frontend" in configured_service_types
        if frontend_service is not None or frontend_stopped or show_configured_frontend:
            self._print_dashboard_service_row(
                label="Frontend",
                service=frontend_service,
                url=str(frontend_url) if frontend_url else None,
                stopped_not_running=frontend_stopped,
                configured_not_running=bool(
                    runs_disabled_dashboard and frontend_service is None and "frontend" in configured_service_types
                ),
                ok_color=green,
                warn_color=yellow,
                bad_color=red,
                label_color=magenta,
                dim=dim,
                reset=reset,
            )
        _print_dashboard_additional_service_rows(
            self,
            project=project,
            project_item=item,
            state=state,
            stopped_for_project=stopped_for_project,
            configured_missing_for_project=configured_missing_for_project,
            runs_disabled_dashboard=runs_disabled_dashboard,
            configured_service_types=configured_service_types,
            ok_color=green,
            warn_color=yellow,
            bad_color=red,
            label_color=cyan,
            dim=dim,
            reset=reset,
        )
        _print_dashboard_ai_session_row(
            self,
            state=state,
            project=project,
            gray=gray,
            dim=dim,
            reset=reset,
            render_launch_fallback=runs_disabled_dashboard or state.mode == "trees",
        )
        if not shared_dependency_grouping:
            _print_dashboard_dependency_rows(
                self,
                state=state,
                project=project,
                ok_color=green,
                warn_color=yellow,
                bad_color=red,
                label_color=cyan,
                reset=reset,
            )
        self._print_dashboard_tests_row(
            state=state,
            project=project,
            ok_color=green,
            bad_color=red,
            dim=dim,
            reset=reset,
        )
        print("")
    if shared_dependency_grouping:
        _print_dashboard_shared_dependency_rows(
            self,
            state=state,
            ok_color=green,
            warn_color=yellow,
            bad_color=red,
            label_color=cyan,
            reset=reset,
        )


def _print_dashboard_service_row(
    self: Any,
    *,
    label: str,
    service: object | None,
    url: str | None,
    configured_not_running: bool,
    stopped_not_running: bool,
    ok_color: str,
    warn_color: str,
    bad_color: str,
    label_color: str,
    dim: str,
    reset: str,
    public_url: str | None = None,
    health_url: str | None = None,
    listener_expected: bool | None = None,
    service_slug: str | None = None,
) -> None:
    slug_suffix = _dashboard_service_slug_suffix(service_slug, dim=dim, reset=reset)
    if configured_not_running:
        label_text = f"{label_color}{label}{reset}{slug_suffix}"
        print(f"    {dim}{STATUS_NEUTRAL}{reset} {label_text}: {dim}not running{reset} {dim}[Configured]{reset}")
        return
    if stopped_not_running:
        label_text = f"{label_color}{label}{reset}{slug_suffix}"
        print(f"    {dim}{STATUS_NEUTRAL}{reset} {label_text}: {dim}not running{reset} {dim}[Stopped]{reset}")
        return
    status = str(getattr(service, "status", "unknown") or "unknown")
    icon, color, status_label = self._dashboard_status_badge(
        status,
        ok_color=ok_color,
        warn_color=warn_color,
        bad_color=bad_color,
    )
    pid = getattr(service, "pid", None)
    pid_suffix = f" (PID: {pid})" if isinstance(pid, int) and pid > 0 else ""
    listener_suffix = ""
    listener_pids = getattr(service, "listener_pids", None)
    if isinstance(listener_pids, list):
        rendered_listener_pids = [
            str(value)
            for value in listener_pids
            if isinstance(value, int) and value > 0 and not (isinstance(pid, int) and value == pid)
        ]
        if rendered_listener_pids:
            listener_suffix = f" [Listener PID: {','.join(rendered_listener_pids)}]"
    if listener_expected is None:
        listener_expected = bool(getattr(service, "listener_expected", True))
    url_text = url or ("n/a" if listener_expected else "non-listener")
    if not url and listener_expected and status.lower() == "unreachable":
        fallback_port = getattr(service, "actual_port", None) or getattr(service, "requested_port", None)
        if isinstance(fallback_port, int) and fallback_port > 0 and isinstance(pid, int) and pid > 0:
            url_text = _dashboard_visual_url(self, fallback_port)
    if service_slug is None:
        raw_slug = str(getattr(service, "service_slug", "") or "").strip().lower()
        raw_type = str(getattr(service, "type", "") or "").strip().lower()
        service_slug = raw_slug or raw_type or None
    slug_suffix = _dashboard_service_slug_suffix(service_slug, dim=dim, reset=reset)
    label_text = f"{label_color}{label}{reset}{slug_suffix}"
    print(
        f"    {color}{icon}{reset} {label_text}: {url_text}{pid_suffix}{listener_suffix} {dim}[{status_label}]{reset}"
    )
    log_path = getattr(service, "log_path", None)
    if isinstance(log_path, str) and log_path.strip():
        rendered_path = render_path_for_terminal(log_path, env=getattr(self, "env", {}), stream=sys.stdout)
        print(f"      {dim}log:{reset} {rendered_path}")
    if public_url is None:
        public_url = str(getattr(service, "public_url", "") or "").strip() or None
    if health_url is None:
        health_url = str(getattr(service, "health_url", "") or "").strip() or None
    if public_url and public_url != url:
        print(f"      {dim}public:{reset} {public_url}")
    if health_url:
        print(f"      {dim}health:{reset} {health_url}")

    requested = getattr(service, "requested_port", None)
    actual = getattr(service, "actual_port", None)
    if isinstance(requested, int) and requested > 0 and isinstance(actual, int) and actual > 0 and requested != actual:
        print(f"      {dim}port: requested {requested} -> actual {actual}{reset}")




def _dashboard_service_slug_suffix(service_slug: str | None, *, dim: str, reset: str) -> str:
    if not service_slug or service_slug in {"backend", "frontend"}:
        return ""
    return f" {dim}({service_slug}){reset}"

def _print_dashboard_additional_service_rows(
    self: Any,
    *,
    project: str,
    project_item: Mapping[str, object],
    state: RunState,
    stopped_for_project: Mapping[str, str],
    configured_missing_for_project: set[str],
    runs_disabled_dashboard: bool,
    configured_service_types: set[str],
    ok_color: str,
    warn_color: str,
    bad_color: str,
    label_color: str,
    dim: str,
    reset: str,
) -> None:
    projected_services = project_item.get("services")
    projected = projected_services if isinstance(projected_services, Mapping) else {}
    slugs: list[str] = []
    for slug in projected:
        normalized = str(slug).strip().lower()
        if normalized and normalized not in {"backend", "frontend"} and normalized not in slugs:
            slugs.append(normalized)
    for slug in sorted(configured_missing_for_project | set(stopped_for_project)):
        if slug not in {"backend", "frontend"} and slug not in slugs:
            slugs.append(slug)
    if runs_disabled_dashboard:
        for slug in sorted(configured_service_types):
            if slug not in {"backend", "frontend"} and slug not in slugs:
                slugs.append(slug)
    for slug in slugs:
        entry_raw = projected.get(slug)
        entry = entry_raw if isinstance(entry_raw, Mapping) else {}
        service_name = str(entry.get("name", "") or "").strip() or stopped_for_project.get(slug, "")
        service = state.services.get(service_name) if service_name else None
        if service is None:
            expected_name = f"{project} {service_display_name(slug)}"
            service = state.services.get(expected_name)
        stopped = service is None and slug in stopped_for_project
        configured = service is None and not stopped and (
            slug in configured_missing_for_project or (runs_disabled_dashboard and slug in configured_service_types)
        )
        if service is None and not stopped and not configured:
            continue
        label = service_display_name(slug)
        url = str(entry.get("url", "") or "").strip() or None
        public_url = str(entry.get("public_url", "") or "").strip() or None
        health_url = str(entry.get("health_url", "") or "").strip() or None
        listener_expected_raw = entry.get("listener_expected")
        listener_expected = bool(listener_expected_raw) if isinstance(listener_expected_raw, bool) else None
        self._print_dashboard_service_row(
            label=label,
            service=service,
            url=url,
            stopped_not_running=stopped,
            configured_not_running=configured,
            ok_color=ok_color,
            warn_color=warn_color,
            bad_color=bad_color,
            label_color=label_color,
            dim=dim,
            reset=reset,
            public_url=public_url,
            health_url=health_url,
            listener_expected=listener_expected,
            service_slug=slug,
        )

def _print_dashboard_dependency_rows(
    self: Any,
    *,
    state: RunState,
    project: str,
    ok_color: str,
    warn_color: str,
    bad_color: str,
    label_color: str,
    reset: str,
) -> None:
    requirements = state.requirements.get(project)
    if requirements is None:
        return
    _print_dashboard_requirement_component_rows(
        self,
        requirements=requirements,
        ok_color=ok_color,
        warn_color=warn_color,
        bad_color=bad_color,
        reset=reset,
    )


def _print_dashboard_shared_dependency_rows(
    self: Any,
    *,
    state: RunState,
    ok_color: str,
    warn_color: str,
    bad_color: str,
    label_color: str,
    reset: str,
) -> None:
    requirements = _dashboard_shared_dependency_requirements(state)
    if requirements is None or not _requirements_has_dashboard_dependencies(requirements):
        return
    print(f"  {label_color}Shared dependencies:{reset}")
    _print_dashboard_requirement_component_rows(
        self,
        requirements=requirements,
        ok_color=ok_color,
        warn_color=warn_color,
        bad_color=bad_color,
        reset=reset,
    )
    print("")


def _print_dashboard_requirement_component_rows(
    self: Any,
    *,
    requirements: RequirementsResult,
    ok_color: str,
    warn_color: str,
    bad_color: str,
    reset: str,
) -> None:
    for definition in dependency_definitions():
        line = _dashboard_dependency_line(
            self,
            requirements=requirements,
            dependency_id=definition.id,
            display_name=definition.display_name,
            ok_color=ok_color,
            warn_color=warn_color,
            bad_color=bad_color,
            reset=reset,
        )
        if line is None:
            continue
        print(line)


def _dashboard_dependency_line(
    self: Any,
    *,
    requirements: RequirementsResult,
    dependency_id: str,
    display_name: str,
    ok_color: str,
    warn_color: str,
    bad_color: str,
    reset: str,
) -> str | None:
    component = requirements.component(dependency_id)
    if not bool(component.get("enabled", False)) or dependency_id == "postgres":
        return None
    port = component.get("final") or component.get("requested")
    runtime_status = str(component.get("runtime_status", "")).strip().lower()
    badge = dependency_status_badge(
        runtime_status,
        success=bool(component.get("success", False)),
        simulated=bool(component.get("simulated", False)),
        failure_count=len(requirements.failures or []),
    )
    color = _dashboard_color_for_severity(
        badge.severity,
        ok_color=ok_color,
        warn_color=warn_color,
        bad_color=bad_color,
    )
    external_url = str(component.get("external_url") or "").strip()
    if badge.severity == "failure":
        url = external_url or "n/a"
    elif external_url:
        url = external_url
    else:
        url = _dashboard_visual_url(self, port) if isinstance(port, int) and port > 0 else "n/a"
    label = f"External {badge.label}" if bool(component.get("external", False)) else badge.label
    return f"    {color}{badge.symbol}{reset} {display_name}: {url} [{label}]"


def _dashboard_dependency_scope(state: RunState) -> str:
    raw = state.metadata.get("dashboard_dependency_scope")
    if isinstance(raw, str) and raw.strip().lower() in {"shared", "isolated", "none"}:
        return raw.strip().lower()
    if _dashboard_legacy_tree_requirements_are_shared(state):
        return "shared"
    return "isolated"


def _dashboard_legacy_tree_requirements_are_shared(state: RunState) -> bool:
    if state.mode != "trees":
        return False
    dependency_projects: set[str] = set()
    dependency_keys: set[str] = set()
    dependency_signatures: set[tuple[tuple[str, tuple[tuple[str, object], ...]], ...]] = set()
    for key, requirements in state.requirements.items():
        if not isinstance(requirements, RequirementsResult):
            continue
        if not _requirements_has_dashboard_dependencies(requirements):
            continue
        requirement_project = str(getattr(requirements, "project", "") or "").strip()
        if requirement_project:
            dependency_projects.add(requirement_project)
        dependency_signatures.add(_dashboard_dependency_signature(requirements))
        dependency_keys.add(str(key).strip())
    if len(dependency_keys) < 2:
        return False
    if not dependency_projects:
        return len(dependency_signatures) == 1
    if not dependency_projects or len(dependency_projects) != 1:
        return False
    shared_project = next(iter(dependency_projects))
    return bool(dependency_keys) and all(key != shared_project for key in dependency_keys)


def _dashboard_dependency_signature(
    requirements: RequirementsResult,
) -> tuple[tuple[str, tuple[tuple[str, object], ...]], ...]:
    signature: list[tuple[str, tuple[tuple[str, object], ...]]] = []
    for definition in dependency_definitions():
        if definition.id == "postgres":
            continue
        component = requirements.component(definition.id)
        if not bool(component.get("enabled", False)):
            continue
        component_signature = tuple(
            (field, component.get(field))
            for field in (
                "enabled",
                "requested",
                "final",
                "runtime_status",
                "success",
                "simulated",
                "container_name",
            )
        )
        signature.append((definition.id, component_signature))
    return tuple(signature)


def _dashboard_shared_dependency_requirements(state: RunState) -> RequirementsResult | None:
    project_raw = state.metadata.get("dashboard_shared_dependency_project")
    project = str(project_raw or "").strip() if isinstance(project_raw, str) else ""
    if project:
        direct = state.requirements.get(project)
        if isinstance(direct, RequirementsResult):
            return direct
        for requirements in state.requirements.values():
            if str(getattr(requirements, "project", "") or "").strip() == project:
                return requirements
    main = state.requirements.get("Main")
    if isinstance(main, RequirementsResult):
        return main
    for requirements in state.requirements.values():
        if _requirements_has_dashboard_dependencies(requirements):
            return requirements
    return None


def _requirements_has_dashboard_dependencies(requirements: RequirementsResult) -> bool:
    for definition in dependency_definitions():
        if definition.id == "postgres":
            continue
        if bool(requirements.component(definition.id).get("enabled", False)):
            return True
    return False


def _print_dashboard_n8n_row(*args: object, **kwargs: object) -> None:
    _print_dashboard_dependency_rows(*args, **kwargs)


def _print_dashboard_tests_row(
    self: Any,
    *,
    state: RunState,
    project: str,
    ok_color: str,
    bad_color: str,
    dim: str,
    reset: str,
) -> None:
    metadata = state.metadata.get("project_test_summaries")
    if not isinstance(metadata, dict):
        return
    entry = metadata.get(project)
    if not isinstance(entry, dict):
        return
    from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator

    summary_raw = DashboardOrchestrator._test_summary_display_path(project_name=project, entry=entry)
    if not summary_raw.strip():
        return
    summary_path = Path(summary_raw).expanduser()
    if not summary_path.is_file():
        return

    status = str(entry.get("status", "")).strip().lower()
    if status not in {"passed", "failed"}:
        try:
            content = summary_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            content = ""
        status = "passed" if "No failed tests." in content else "failed"
    passed = status == "passed"
    icon = "✓" if passed else "✗"
    color = ok_color if passed else bad_color
    timestamp = datetime.fromtimestamp(summary_path.stat().st_mtime).strftime("%b %d %H:%M")
    rendered_path = render_path_for_terminal(summary_path, env=getattr(self, "env", {}), stream=sys.stdout)
    print(f"      {color}{icon}{reset} tests: {rendered_path} {dim}({timestamp}){reset}")
    raw_excerpt = entry.get("summary_excerpt")
    if isinstance(raw_excerpt, list):
        rendered_excerpt = [str(line).strip() for line in raw_excerpt if str(line).strip()]
        for line in rendered_excerpt[:3]:
            print(f"        {line}")


def _dashboard_project_pr(self: Any, *, state: RunState, project: str) -> tuple[str, str] | None:
    if not _dashboard_pr_lookup_enabled(self):
        return None
    project_root = _dashboard_project_root(self, state=state, project=project)
    if project_root is None:
        return None
    return _dashboard_lookup_pr(self, project=project, project_root=project_root)


def _dashboard_project_pr_map(self: Any, *, state: RunState, projects: list[str]) -> dict[str, tuple[str, str] | None]:
    if not projects or not _dashboard_pr_lookup_enabled(self):
        return {}
    if len(projects) <= 1:
        project = projects[0]
        return {project: _dashboard_project_pr(self, state=state, project=project)}

    results: dict[str, tuple[str, str] | None] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(projects))) as executor:
        future_map = {
            executor.submit(_dashboard_project_pr, self, state=state, project=project): project for project in projects
        }
        for future in concurrent.futures.as_completed(future_map):
            results[future_map[future]] = future.result()
    return results


def _dashboard_pr_lookup_enabled(self: Any) -> bool:
    env = getattr(self, "env", {})
    if not isinstance(env, dict):
        return True
    raw = str(env.get("ENVCTL_DASHBOARD_PR_LINKS", "")).strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def _dashboard_visual_url(self: Any, port: int) -> str:
    return f"http://{_dashboard_visual_host(self)}:{port}"


def _dashboard_visual_host(self: Any) -> str:
    visual_raw: object | None = None
    public_raw: object | None = None
    runtime_env = getattr(self, "env", {})
    if isinstance(runtime_env, Mapping):
        visual_raw = runtime_env.get(_DASHBOARD_VISUAL_HOST_ENV)
        public_raw = runtime_env.get(_DASHBOARD_PUBLIC_HOST_ENV)
    if visual_raw is None or public_raw is None:
        config_raw = getattr(getattr(self, "config", None), "raw", {})
        if isinstance(config_raw, Mapping):
            if visual_raw is None:
                visual_raw = config_raw.get(_DASHBOARD_VISUAL_HOST_ENV)
            if public_raw is None:
                public_raw = config_raw.get(_DASHBOARD_PUBLIC_HOST_ENV)
    host = str(visual_raw or "").strip() or str(public_raw or "").strip()
    return host or "localhost"


def _dashboard_pr_cache_ttl_seconds(self: Any) -> float:
    env = getattr(self, "env", {})
    if not isinstance(env, dict):
        return 60.0
    raw = str(env.get("ENVCTL_DASHBOARD_PR_CACHE_SECONDS", "60")).strip()
    try:
        parsed = float(raw)
    except ValueError:
        return 60.0
    if parsed <= 0:
        return 0.0
    return parsed


def _dashboard_project_root(self: Any, *, state: RunState, project: str) -> Path | None:
    metadata_roots = state.metadata.get("project_roots")
    if isinstance(metadata_roots, dict):
        root_raw = metadata_roots.get(project)
        if isinstance(root_raw, str) and root_raw.strip():
            return Path(root_raw).expanduser()

    for service_suffix in (" Backend", " Frontend"):
        service = state.services.get(f"{project}{service_suffix}")
        cwd_raw = getattr(service, "cwd", None)
        if not isinstance(cwd_raw, str) or not cwd_raw.strip():
            continue
        cwd_path = Path(cwd_raw).expanduser()
        if cwd_path.name.lower() in {"backend", "frontend"}:
            return cwd_path.parent
        return cwd_path

    if project.strip().lower() == "main":
        base_dir = getattr(getattr(self, "config", None), "base_dir", None)
        if isinstance(base_dir, Path):
            return base_dir
        if isinstance(base_dir, str) and base_dir.strip():
            return Path(base_dir).expanduser()
    return None


def _dashboard_configured_service_types(state: RunState) -> set[str]:
    return set(normalize_dashboard_service_types(state.metadata.get("dashboard_configured_service_types")))


def _dashboard_project_configured_services(state: RunState) -> dict[str, set[str]]:
    return dashboard_project_configured_services_from_metadata(state.metadata)


def _dashboard_configured_service_total(*, projection: Mapping[str, object], configured_service_types: set[str]) -> int:
    if not projection or not configured_service_types:
        return 0
    return sum(len(configured_service_types) for _project in projection)


def _dashboard_stopped_services_by_project(state: RunState) -> dict[str, dict[str, str]]:
    raw = state.metadata.get("dashboard_stopped_services")
    if not isinstance(raw, list):
        return {}
    stopped: dict[str, dict[str, str]] = {}
    for item in raw:
        if not isinstance(item, Mapping):
            continue
        project = str(item.get("project", "") or "").strip()
        service_type = str(item.get("type", "") or "").strip().lower()
        name = str(item.get("name", "") or "").strip()
        if not project or not service_type:
            continue
        stopped.setdefault(project, {})[service_type] = name
    return stopped


def _dashboard_visible_stopped_service_count(
    state: RunState,
    *,
    stopped_services: Mapping[str, Mapping[str, str]],
    configured_missing_services: Mapping[str, set[str]] | None = None,
) -> int:
    seen: set[str] = set()
    count = 0
    for project, services in stopped_services.items():
        for service_type, stopped_name in services.items():
            service_name = stopped_name or f"{project} {service_type.title()}"
            if service_name not in state.services and service_name not in seen:
                seen.add(service_name)
                count += 1
    for project, service_types in (configured_missing_services or {}).items():
        for service_type in service_types:
            service_name = f"{project} {service_type.title()}"
            if service_name not in state.services and service_name not in seen:
                seen.add(service_name)
                count += 1
    return count


def _dashboard_runs_disabled(state: RunState) -> bool:
    raw = state.metadata.get("dashboard_runs_disabled")
    if isinstance(raw, bool):
        return raw
    dashboard_banner = state.metadata.get("dashboard_banner")
    if not isinstance(dashboard_banner, str):
        return False
    return "runs are disabled" in dashboard_banner.lower()


def _dashboard_relative_component_path(project_root: Path, component_path: Path) -> str:
    try:
        relative = component_path.relative_to(project_root)
    except ValueError:
        return str(component_path)
    if str(relative) == ".":
        return "."
    return str(relative)


def _dashboard_lookup_pr(self: Any, *, project: str, project_root: Path) -> tuple[str, str] | None:
    if not project_root.exists():
        return None

    process_runner = getattr(self, "process_runner", None)
    run_cmd = getattr(process_runner, "run", None)
    if not callable(run_cmd):
        return None

    cache = getattr(self, "_dashboard_pr_url_cache", None)
    if not isinstance(cache, dict):
        cache = {}
        setattr(self, "_dashboard_pr_url_cache", cache)
    now = time.monotonic()
    gh_bin = shutil.which("gh")
    if gh_bin is None:
        return None

    try:
        branch_result = run_cmd(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=project_root,
            timeout=1.5,
        )
        head_result = run_cmd(
            ["git", "rev-parse", "HEAD"],
            cwd=project_root,
            timeout=1.5,
        )
    except Exception:
        return None
    branch = _first_non_empty_line(getattr(branch_result, "stdout", ""))
    head_oid = _first_non_empty_line(getattr(head_result, "stdout", ""))
    if int(getattr(branch_result, "returncode", 1)) != 0 or not branch or branch == "HEAD":
        return None
    if int(getattr(head_result, "returncode", 1)) != 0 or not head_oid:
        return None

    cache_key = f"{project}|{project_root}|{branch}|{head_oid}"
    cache_entry = cache.get(cache_key)
    if isinstance(cache_entry, tuple) and len(cache_entry) == 2:
        expiry_raw, cached_pr = cache_entry
        if isinstance(expiry_raw, (int, float)) and now <= float(expiry_raw):
            if isinstance(cached_pr, tuple) and len(cached_pr) == 2:
                url_raw, state_raw = cached_pr
                if isinstance(url_raw, str) and isinstance(state_raw, str):
                    return (url_raw, state_raw)
            return None

    try:
        pr_result = run_cmd(
            [gh_bin, "pr", "list", "--head", branch, "--state", "all", "--json", "url,state,mergedAt,headRefOid"],
            cwd=project_root,
            timeout=2.5,
        )
    except Exception:
        cache[cache_key] = (now + _dashboard_pr_cache_ttl_seconds(self), None)
        return None
    if int(getattr(pr_result, "returncode", 1)) != 0:
        cache[cache_key] = (now + _dashboard_pr_cache_ttl_seconds(self), None)
        return None
    pr_info = _select_dashboard_pr(getattr(pr_result, "stdout", ""), head_oid=head_oid)
    cache[cache_key] = (now + _dashboard_pr_cache_ttl_seconds(self), pr_info)
    return pr_info


def _select_dashboard_pr(raw: object, *, head_oid: str) -> tuple[str, str] | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None

    merged_candidate: tuple[str, str] | None = None
    normalized_head_oid = head_oid.strip()
    for item in payload:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url", "") or "").strip()
        if not url.lower().startswith(("http://", "https://")):
            continue
        state = str(item.get("state", "") or "").strip().upper()
        if state == "OPEN":
            return (url, "active")
        if state == "MERGED":
            merged_at = str(item.get("mergedAt", "") or "").strip()
            pr_head_oid = str(item.get("headRefOid", "") or "").strip()
            if merged_at and pr_head_oid and pr_head_oid == normalized_head_oid and merged_candidate is None:
                merged_candidate = (url, "merged")
    return merged_candidate


def _first_non_empty_line(value: object) -> str:
    if not isinstance(value, str):
        return ""
    for raw_line in value.splitlines():
        line = raw_line.strip()
        if line:
            return line
    return ""


def _dashboard_status_badge(
    status: str,
    *,
    ok_color: str,
    warn_color: str,
    bad_color: str,
) -> tuple[str, str, str]:
    lowered = status.strip().lower()
    badge = service_status_badge(lowered)
    return (
        badge.symbol,
        _dashboard_color_for_severity(
            badge.severity,
            ok_color=ok_color,
            warn_color=warn_color,
            bad_color=bad_color,
        ),
        badge.label,
    )


def _dashboard_color_for_severity(
    severity: str,
    *,
    ok_color: str,
    warn_color: str,
    bad_color: str,
) -> str:
    if severity == "success":
        return ok_color
    if severity in {"warning", "neutral"}:
        return warn_color
    return bad_color


def _dashboard_palette(self: Any) -> dict[str, str]:
    interactive_tty = False
    can_interactive_tty = getattr(self, "_can_interactive_tty", None)
    if callable(can_interactive_tty):
        try:
            interactive_tty = bool(can_interactive_tty())
        except Exception:
            interactive_tty = False
    enabled = colors_enabled(
        getattr(self, "env", {}),
        stream=sys.stdout,
        interactive_tty=interactive_tty,
    )
    if not enabled:
        return {
            "reset": "",
            "bold": "",
            "dim": "",
            "cyan": "",
            "green": "",
            "yellow": "",
            "red": "",
            "blue": "",
            "magenta": "",
            "gray": "",
        }
    return {
        "reset": "\033[0m",
        "bold": "\033[1m",
        "dim": "\033[2m",
        "cyan": "\033[36m",
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "gray": "\033[90m",
    }


def _print_dashboard_ai_session_row(
    self: Any,
    *,
    state: RunState,
    project: str,
    gray: str,
    dim: str,
    reset: str,
    render_launch_fallback: bool,
) -> None:
    import subprocess  # noqa: PLC0415
    from envctl_engine.planning.plan_agent.workflow import resolve_plan_agent_launch_command  # noqa: PLC0415
    from envctl_engine.runtime.session_management import list_tmux_sessions  # noqa: PLC0415

    project_root = _dashboard_project_root(self, state=state, project=project)
    repo_root = _dashboard_repo_root_for_project(project_root=project_root)
    envctl_executable = "envctl"
    launch_command = None
    if project_root is not None and repo_root is not None:
        launch_command = resolve_plan_agent_launch_command(
            project_name=project,
            project_root=project_root,
            repo_root=repo_root,
            envctl_executable=envctl_executable,
        )
    if launch_command is None and project_root is not None:
        launch_command = _dashboard_worktree_ai_launch_command(
            project_root=project_root,
            envctl_executable=envctl_executable,
        )
    sessions = list_tmux_sessions()
    matching = [
        session
        for session in sessions
        if _dashboard_session_matches_project(project_root=project_root, project=project, session=session)
    ]
    current_session, current_path = _dashboard_current_tmux_target(subprocess_module=subprocess)
    if matching:
        for session in matching:
            if _dashboard_session_is_attached(
                project_root=project_root,
                session=session,
                current_session=current_session,
                current_path=current_path,
            ):
                session_message = "attached"
            else:
                session_message = "detached"
            print(f"    {gray}AI session:{reset} {dim}{session['attach']} ({session_message}){reset}")
        return
    if not render_launch_fallback or not launch_command:
        return
    print(f"    {dim}○{reset} {gray}Run AI:{reset} {dim}{launch_command}{reset}")


def _dashboard_session_matches_project(*, project_root: Path | None, project: str, session: dict[str, str]) -> bool:
    if project_root is not None and _dashboard_session_matches_project_root(project_root=project_root, session=session):
        return True
    if project_root is not None and _dashboard_session_name_matches_envctl_plan_agent(
        project_root=project_root,
        project=project,
        session_name=str(session.get("name", "") or ""),
    ):
        return True
    if _dashboard_session_name_matches_project(project=project, session_name=str(session.get("name", "") or "")):
        return True
    return _dashboard_window_matches_project(project=project, window_name=str(session.get("windows", "") or ""))


def _dashboard_session_is_attached(
    *,
    project_root: Path | None,
    session: dict[str, str],
    current_session: str,
    current_path: str,
) -> bool:
    if str(session.get("name", "") or "").strip() != current_session:
        return False
    if project_root is None:
        return False
    return _dashboard_path_matches_project_root(project_root=project_root, candidate_path=current_path)


def _dashboard_window_matches_project(*, project: str, window_name: str) -> bool:
    from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree  # noqa: PLC0415
    from envctl_engine.planning.plan_agent.tmux_transport import _tmux_window_name_for_worktree  # noqa: PLC0415

    expected_window = _tmux_window_name_for_worktree(CreatedPlanWorktree(name=project, root=Path("."), plan_file=""))
    normalized_expected = str(expected_window).strip().lower()
    normalized_windows = {part.strip().lower() for part in str(window_name).split(",") if part.strip()}
    return normalized_expected in normalized_windows


def _dashboard_session_name_matches_envctl_plan_agent(*, project_root: Path, project: str, session_name: str) -> bool:
    from envctl_engine.planning.plan_agent.models import CreatedPlanWorktree  # noqa: PLC0415
    from envctl_engine.planning.plan_agent.tmux_transport import _tmux_session_name_for_worktree  # noqa: PLC0415

    normalized_session = str(session_name or "").strip().lower()
    if not normalized_session:
        return False
    repo_root = _dashboard_repo_root_for_project(project_root=project_root)
    if repo_root is None:
        return False
    try:
        worktree = CreatedPlanWorktree(name=project, root=project_root, plan_file="")
        expected_names = {
            _tmux_session_name_for_worktree(repo_root, worktree, cli=cli).lower()
            for cli in ("codex", "opencode")
        }
    except (OSError, ValueError):
        return False
    return any(
        normalized_session == expected or normalized_session.startswith(f"{expected}-") for expected in expected_names
    )


def _dashboard_session_name_matches_project(*, project: str, session_name: str) -> bool:
    project_feature = _dashboard_project_feature_slug(project)
    session_feature = _dashboard_omx_session_feature_slug(session_name)
    return bool(project_feature and session_feature and project_feature == session_feature)


def _dashboard_project_feature_slug(project: str) -> str:
    normalized = str(project or "").strip()
    normalized = re.sub(r"-\d+$", "", normalized)
    return _dashboard_normalized_feature_slug(normalized)


def _dashboard_omx_session_feature_slug(session_name: str) -> str:
    normalized = str(session_name or "").strip().lower()
    match = re.fullmatch(r"omx-\d+-(?P<feature>.+)-\d+-[a-z0-9]+", normalized)
    if match is None:
        return ""
    feature = re.sub(r"-\d+$", "", match.group("feature"))
    return _dashboard_normalized_feature_slug(feature)


def _dashboard_normalized_feature_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")


def _dashboard_project_root_from_state(*, state: RunState, project: str) -> Path | None:
    metadata_roots = state.metadata.get("project_roots")
    if not isinstance(metadata_roots, dict):
        return None
    root_raw = str(metadata_roots.get(project, "") or "").strip()
    if not root_raw:
        return None
    return Path(root_raw).expanduser().resolve(strict=False)


def _dashboard_repo_root_for_project(*, project_root: Path | None) -> Path | None:
    if project_root is None:
        return None
    provenance_repo_root = _dashboard_repo_root_from_provenance(project_root=project_root)
    if provenance_repo_root is not None:
        return provenance_repo_root
    tree_layout_repo_root = _dashboard_repo_root_from_tree_layout(project_root=project_root)
    if tree_layout_repo_root is not None:
        return tree_layout_repo_root
    current = project_root.expanduser()
    for candidate in (current, *current.parents):
        if (candidate / "todo" / "plans").is_dir() or (candidate / "todo" / "done").is_dir():
            return candidate
    for candidate in (current, *current.parents):
        if (candidate / "todo").is_dir():
            return candidate
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def _dashboard_repo_root_from_provenance(*, project_root: Path) -> Path | None:
    provenance_path = project_root / ".envctl-state" / "worktree-provenance.json"
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(provenance, dict):
        return None
    repo_root_raw = str(provenance.get("created_from_repo", "") or "").strip()
    if not repo_root_raw:
        return None
    repo_root = Path(repo_root_raw).expanduser()
    if (repo_root / ".git").exists() or (repo_root / "todo").is_dir():
        return repo_root
    return None


def _dashboard_repo_root_from_tree_layout(*, project_root: Path) -> Path | None:
    current = project_root.expanduser()
    for trees_dir in current.parents:
        if trees_dir.name != "trees":
            continue
        repo_root = trees_dir.parent
        if repo_root == current:
            continue
        try:
            current.relative_to(trees_dir)
        except ValueError:
            continue
        if (repo_root / "todo" / "plans").is_dir() or (repo_root / "todo" / "done").is_dir():
            return repo_root
        if (repo_root / ".git").exists() and (repo_root / "todo").is_dir():
            return repo_root
    return None


def _dashboard_worktree_ai_launch_command(*, project_root: Path, envctl_executable: str) -> str | None:
    root = project_root.expanduser()
    if not (root / "MAIN_TASK.md").is_file():
        return None
    return " ".join(
        (
            shlex.quote(envctl_executable),
            "--repo",
            shlex.quote(_dashboard_cli_display_path(root)),
            "codex-tmux",
        )
    )


def _dashboard_cli_display_path(path: Path) -> str:
    raw = str(path)
    if raw.startswith("/private/var/"):
        return raw.removeprefix("/private")
    return raw


def _dashboard_session_matches_project_root(*, project_root: Path, session: dict[str, str]) -> bool:
    paths_raw = str(session.get("paths", "") or "")
    if not paths_raw:
        return False
    for raw_path in paths_raw.splitlines():
        candidate = str(raw_path).strip()
        if not candidate:
            continue
        if _dashboard_path_matches_project_root(project_root=project_root, candidate_path=candidate):
            return True
    return False


def _dashboard_path_matches_project_root(*, project_root: Path, candidate_path: str) -> bool:
    normalized_project_root = str(project_root.resolve(strict=False))
    normalized_candidate = str(candidate_path).replace(" (deleted)", "").strip()
    if not normalized_candidate:
        return False
    try:
        resolved_candidate = str(Path(normalized_candidate).expanduser().resolve(strict=False))
    except Exception:
        resolved_candidate = normalized_candidate
    if resolved_candidate == normalized_project_root:
        return True
    return resolved_candidate.startswith(f"{normalized_project_root}/")


def _dashboard_current_tmux_target(*, subprocess_module: Any) -> tuple[str, str]:
    try:
        result = subprocess_module.run(
            ["tmux", "display-message", "-p", "#{session_name}\n#{pane_current_path}"],
            capture_output=True,
            text=True,
            timeout=2.0,
        )
    except Exception:
        return "", ""
    if result.returncode != 0:
        return "", ""
    lines = [line.strip() for line in str(result.stdout or "").splitlines() if line.strip()]
    if len(lines) < 2:
        return "", ""
    return lines[0], lines[1]
