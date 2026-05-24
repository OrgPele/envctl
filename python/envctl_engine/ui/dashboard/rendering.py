from __future__ import annotations

# pyright: reportUnusedFunction=false

from datetime import datetime
import sys
from pathlib import Path
from typing import Any, Mapping, cast

from envctl_engine.dashboard_metadata import (
    DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY,
    dashboard_configured_missing_services_by_project,
)
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.ui.color_policy import colors_enabled
from envctl_engine.ui.path_links import render_path_for_terminal
from envctl_engine.ui.dashboard.failure_detail_support import summary_display_path
from envctl_engine.ui.status_symbols import (
    service_status_badge,
)
from envctl_engine.ui.dashboard import ai_session_rendering
from envctl_engine.ui.dashboard import dependency_rendering
from envctl_engine.ui.dashboard import pr_link_rendering
from envctl_engine.ui.dashboard import service_rendering

_DASHBOARD_VISUAL_HOST_ENV = "ENVCTL_UI_VISUAL_HOST"
_DASHBOARD_PUBLIC_HOST_ENV = "ENVCTL_PUBLIC_HOST"
shutil = pr_link_rendering.shutil


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
    service_rendering.print_dashboard_service_row(
        self,
        label=label,
        service=service,
        url=url,
        configured_not_running=configured_not_running,
        stopped_not_running=stopped_not_running,
        ok_color=ok_color,
        warn_color=warn_color,
        bad_color=bad_color,
        label_color=label_color,
        dim=dim,
        reset=reset,
        public_url=public_url,
        health_url=health_url,
        listener_expected=listener_expected,
        service_slug=service_slug,
        visual_url_fn=_dashboard_visual_url,
        status_badge_fn=lambda status: _dashboard_status_badge(
            status,
            ok_color=ok_color,
            warn_color=warn_color,
            bad_color=bad_color,
        ),
    )


def _dashboard_service_slug_suffix(service_slug: str | None, *, dim: str, reset: str) -> str:
    return service_rendering.dashboard_service_slug_suffix(service_slug, dim=dim, reset=reset)

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
    service_rendering.print_dashboard_additional_service_rows(
        self,
        project=project,
        project_item=project_item,
        state=state,
        stopped_for_project=stopped_for_project,
        configured_missing_for_project=configured_missing_for_project,
        runs_disabled_dashboard=runs_disabled_dashboard,
        configured_service_types=configured_service_types,
        ok_color=ok_color,
        warn_color=warn_color,
        bad_color=bad_color,
        label_color=label_color,
        dim=dim,
        reset=reset,
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
    dependency_rendering.print_dashboard_dependency_rows(
        self,
        state=state,
        project=project,
        ok_color=ok_color,
        warn_color=warn_color,
        bad_color=bad_color,
        label_color=label_color,
        reset=reset,
        visual_url_fn=_dashboard_visual_url,
        severity_color_fn=lambda severity: _dashboard_color_for_severity(
            severity,
            ok_color=ok_color,
            warn_color=warn_color,
            bad_color=bad_color,
        ),
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
    dependency_rendering.print_dashboard_shared_dependency_rows(
        self,
        state=state,
        ok_color=ok_color,
        warn_color=warn_color,
        bad_color=bad_color,
        label_color=label_color,
        reset=reset,
        visual_url_fn=_dashboard_visual_url,
        severity_color_fn=lambda severity: _dashboard_color_for_severity(
            severity,
            ok_color=ok_color,
            warn_color=warn_color,
            bad_color=bad_color,
        ),
    )


def _print_dashboard_requirement_component_rows(
    self: Any,
    *,
    requirements: RequirementsResult,
    ok_color: str,
    warn_color: str,
    bad_color: str,
    reset: str,
) -> None:
    dependency_rendering.print_dashboard_requirement_component_rows(
        self,
        requirements=requirements,
        ok_color=ok_color,
        warn_color=warn_color,
        bad_color=bad_color,
        reset=reset,
        visual_url_fn=_dashboard_visual_url,
        severity_color_fn=lambda severity: _dashboard_color_for_severity(
            severity,
            ok_color=ok_color,
            warn_color=warn_color,
            bad_color=bad_color,
        ),
    )


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
    return dependency_rendering.dashboard_dependency_line(
        self,
        requirements=requirements,
        dependency_id=dependency_id,
        display_name=display_name,
        reset=reset,
        visual_url_fn=_dashboard_visual_url,
        severity_color_fn=lambda severity: _dashboard_color_for_severity(
            severity,
            ok_color=ok_color,
            warn_color=warn_color,
            bad_color=bad_color,
        ),
    )


def _dashboard_dependency_scope(state: RunState) -> str:
    return dependency_rendering.dashboard_dependency_scope(state)


def _dashboard_legacy_tree_requirements_are_shared(state: RunState) -> bool:
    return dependency_rendering.dashboard_legacy_tree_requirements_are_shared(state)


def _dashboard_dependency_signature(
    requirements: RequirementsResult,
) -> tuple[tuple[str, tuple[tuple[str, object], ...]], ...]:
    return dependency_rendering.dashboard_dependency_signature(requirements)


def _dashboard_shared_dependency_requirements(state: RunState) -> RequirementsResult | None:
    return dependency_rendering.dashboard_shared_dependency_requirements(state)


def _requirements_has_dashboard_dependencies(requirements: RequirementsResult) -> bool:
    return dependency_rendering.requirements_has_dashboard_dependencies(requirements)


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

    summary_raw = summary_display_path(project_name=project, entry=entry)
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
    return pr_link_rendering.dashboard_project_pr(self, state=state, project=project)


def _dashboard_project_pr_map(self: Any, *, state: RunState, projects: list[str]) -> dict[str, tuple[str, str] | None]:
    return pr_link_rendering.dashboard_project_pr_map(self, state=state, projects=projects)


def _dashboard_pr_lookup_enabled(self: Any) -> bool:
    return pr_link_rendering.dashboard_pr_lookup_enabled(self)


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
    return pr_link_rendering.dashboard_pr_cache_ttl_seconds(self)


def _dashboard_project_root(self: Any, *, state: RunState, project: str) -> Path | None:
    return pr_link_rendering.dashboard_project_root(self, state=state, project=project)


def _dashboard_configured_service_types(state: RunState) -> set[str]:
    return service_rendering.dashboard_configured_service_types(state)


def _dashboard_project_configured_services(state: RunState) -> dict[str, set[str]]:
    return service_rendering.dashboard_project_configured_services(state)


def _dashboard_configured_service_total(*, projection: Mapping[str, object], configured_service_types: set[str]) -> int:
    return service_rendering.dashboard_configured_service_total(
        projection=projection,
        configured_service_types=configured_service_types,
    )


def _dashboard_stopped_services_by_project(state: RunState) -> dict[str, dict[str, str]]:
    return service_rendering.dashboard_stopped_services_by_project(state)


def _dashboard_visible_stopped_service_count(
    state: RunState,
    *,
    stopped_services: Mapping[str, Mapping[str, str]],
    configured_missing_services: Mapping[str, set[str]] | None = None,
) -> int:
    return service_rendering.dashboard_visible_stopped_service_count(
        state,
        stopped_services=stopped_services,
        configured_missing_services=configured_missing_services,
    )


def _dashboard_runs_disabled(state: RunState) -> bool:
    return service_rendering.dashboard_runs_disabled(state)


def _dashboard_relative_component_path(project_root: Path, component_path: Path) -> str:
    return pr_link_rendering.dashboard_relative_component_path(project_root, component_path)


def _dashboard_lookup_pr(self: Any, *, project: str, project_root: Path) -> tuple[str, str] | None:
    return pr_link_rendering.dashboard_lookup_pr(self, project=project, project_root=project_root)


def _select_dashboard_pr(raw: object, *, head_oid: str) -> tuple[str, str] | None:
    return pr_link_rendering.select_dashboard_pr(raw, head_oid=head_oid)


def _first_non_empty_line(value: object) -> str:
    return pr_link_rendering.first_non_empty_line(value)


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
    ai_session_rendering.print_dashboard_ai_session_row(
        self,
        state=state,
        project=project,
        gray=gray,
        dim=dim,
        reset=reset,
        render_launch_fallback=render_launch_fallback,
        project_root_fn=_dashboard_project_root,
        current_tmux_target_fn=_dashboard_current_tmux_target,
    )


_dashboard_session_matches_project = ai_session_rendering._dashboard_session_matches_project
_dashboard_session_is_attached = ai_session_rendering._dashboard_session_is_attached
_dashboard_window_matches_project = ai_session_rendering._dashboard_window_matches_project
_dashboard_session_name_matches_envctl_plan_agent = (
    ai_session_rendering._dashboard_session_name_matches_envctl_plan_agent
)
_dashboard_session_name_matches_project = ai_session_rendering._dashboard_session_name_matches_project
_dashboard_project_feature_slug = ai_session_rendering._dashboard_project_feature_slug
_dashboard_omx_session_feature_slug = ai_session_rendering._dashboard_omx_session_feature_slug
_dashboard_normalized_feature_slug = ai_session_rendering._dashboard_normalized_feature_slug
_dashboard_project_root_from_state = ai_session_rendering._dashboard_project_root_from_state
_dashboard_repo_root_for_project = ai_session_rendering.dashboard_repo_root_for_project
_dashboard_repo_root_from_provenance = ai_session_rendering._dashboard_repo_root_from_provenance
_dashboard_repo_root_from_tree_layout = ai_session_rendering._dashboard_repo_root_from_tree_layout
_dashboard_worktree_ai_launch_command = ai_session_rendering._dashboard_worktree_ai_launch_command
_dashboard_cli_display_path = ai_session_rendering._dashboard_cli_display_path
_dashboard_session_matches_project_root = ai_session_rendering._dashboard_session_matches_project_root
_dashboard_path_matches_project_root = ai_session_rendering._dashboard_path_matches_project_root


def _dashboard_current_tmux_target(*, subprocess_module: Any) -> tuple[str, str]:
    return ai_session_rendering.dashboard_current_tmux_target(subprocess_module=subprocess_module)
