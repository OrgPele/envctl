from __future__ import annotations

import sys
from typing import Any, Callable, Mapping

from envctl_engine.dashboard_metadata import (
    dashboard_project_configured_services_from_metadata,
    normalize_dashboard_service_types,
)
from envctl_engine.shared.services import service_display_name
from envctl_engine.state.models import RunState
from envctl_engine.ui.path_links import render_path_for_terminal
from envctl_engine.ui.status_symbols import STATUS_NEUTRAL


VisualUrlFn = Callable[[Any, int], str]
StatusBadgeFn = Callable[[str], tuple[str, str, str]]


def print_dashboard_service_row(
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
    visual_url_fn: VisualUrlFn,
    status_badge_fn: StatusBadgeFn,
) -> None:
    _ = ok_color, warn_color, bad_color
    slug_suffix = dashboard_service_slug_suffix(service_slug, dim=dim, reset=reset)
    if configured_not_running:
        label_text = f"{label_color}{label}{reset}{slug_suffix}"
        print(f"    {dim}{STATUS_NEUTRAL}{reset} {label_text}: {dim}not running{reset} {dim}[Configured]{reset}")
        return
    if stopped_not_running:
        label_text = f"{label_color}{label}{reset}{slug_suffix}"
        print(f"    {dim}{STATUS_NEUTRAL}{reset} {label_text}: {dim}not running{reset} {dim}[Stopped]{reset}")
        return
    status = str(getattr(service, "status", "unknown") or "unknown")
    icon, color, status_label = status_badge_fn(status)
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
            url_text = visual_url_fn(self, fallback_port)
    if service_slug is None:
        raw_slug = str(getattr(service, "service_slug", "") or "").strip().lower()
        raw_type = str(getattr(service, "type", "") or "").strip().lower()
        service_slug = raw_slug or raw_type or None
    slug_suffix = dashboard_service_slug_suffix(service_slug, dim=dim, reset=reset)
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


def dashboard_service_slug_suffix(service_slug: str | None, *, dim: str, reset: str) -> str:
    if not service_slug or service_slug in {"backend", "frontend"}:
        return ""
    return f" {dim}({service_slug}){reset}"


def print_dashboard_additional_service_rows(
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


def dashboard_configured_service_types(state: RunState) -> set[str]:
    return set(normalize_dashboard_service_types(state.metadata.get("dashboard_configured_service_types")))


def dashboard_project_configured_services(state: RunState) -> dict[str, set[str]]:
    return dashboard_project_configured_services_from_metadata(state.metadata)


def dashboard_configured_service_total(*, projection: Mapping[str, object], configured_service_types: set[str]) -> int:
    if not projection or not configured_service_types:
        return 0
    return sum(len(configured_service_types) for _project in projection)


def dashboard_stopped_services_by_project(state: RunState) -> dict[str, dict[str, str]]:
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


def dashboard_visible_stopped_service_count(
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


def dashboard_runs_disabled(state: RunState) -> bool:
    raw = state.metadata.get("dashboard_runs_disabled")
    if isinstance(raw, bool):
        return raw
    dashboard_banner = state.metadata.get("dashboard_banner")
    if not isinstance(dashboard_banner, str):
        return False
    return "runs are disabled" in dashboard_banner.lower()
