from __future__ import annotations

from datetime import datetime
import sys
from pathlib import Path
from typing import Any, Mapping, cast

from envctl_engine.state.models import RequirementsResult, RunState
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
from envctl_engine.ui.dashboard import snapshot_rendering

_DASHBOARD_VISUAL_HOST_ENV = "ENVCTL_UI_VISUAL_HOST"
_DASHBOARD_PUBLIC_HOST_ENV = "ENVCTL_PUBLIC_HOST"
shutil = pr_link_rendering.shutil


def _print_dashboard_snapshot(self: Any, state: RunState) -> None:
    reconcile_for_snapshot = getattr(self, "_dashboard_reconcile_for_snapshot", None)
    if callable(reconcile_for_snapshot):
        def reconcile_fn(current_state: RunState) -> list[str]:
            return list(cast(list[str], reconcile_for_snapshot(current_state)))
    else:
        reconcile_fn = self._reconcile_state_truth

    current_session_id = getattr(self, "_current_session_id", None)

    def session_id_fn() -> str | None:
        session_id = current_session_id() if callable(current_session_id) else None
        return session_id if isinstance(session_id, str) else None

    def project_pr_map_fn(current_state: RunState, projects: list[str]) -> Mapping[str, tuple[str, str]]:
        return _dashboard_project_pr_map(self, state=current_state, projects=projects)

    hooks = snapshot_rendering.DashboardSnapshotRenderHooks(
        terminal_size=self._terminal_size,
        palette=self._dashboard_palette,
        truncate_text=self._truncate_text,
        current_session_id=session_id_fn,
        visual_host=lambda: _dashboard_visual_host(self),
        reconcile_state_truth=reconcile_fn,
        emit=self._emit,
        project_pr_map=project_pr_map_fn,
        print_service_row=self._print_dashboard_service_row,
        print_additional_service_rows=lambda **kwargs: _print_dashboard_additional_service_rows(self, **kwargs),
        print_ai_session_row=lambda **kwargs: _print_dashboard_ai_session_row(self, **kwargs),
        print_dependency_rows=lambda **kwargs: _print_dashboard_dependency_rows(self, **kwargs),
        print_shared_dependency_rows=lambda **kwargs: _print_dashboard_shared_dependency_rows(self, **kwargs),
        print_tests_row=self._print_dashboard_tests_row,
    )
    snapshot_rendering.DashboardSnapshotPrinter(hooks).print_snapshot(state)


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
