from __future__ import annotations

# pyright: reportUnusedFunction=false

import concurrent.futures
from datetime import datetime
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any, cast

from envctl_engine.state.models import RunState
from envctl_engine.requirements.core import dependency_definitions
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.ui.color_policy import colors_enabled


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
    runtime_map = build_runtime_map(state)
    projection = runtime_map.get("projection", {})
    if not isinstance(projection, dict):
        projection = {}
    if not projection:
        metadata_roots = state.metadata.get("project_roots")
        if isinstance(metadata_roots, dict):
            projection = {str(project).strip(): {} for project in metadata_roots if str(project).strip()}
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
    service_statuses = [
        str(getattr(service, "status", "unknown") or "unknown").strip().lower() for service in state.services.values()
    ]
    total_services = len(service_statuses)
    running_services = sum(1 for status in service_statuses if status in {"running", "healthy"})
    issue_services = sum(1 for status in service_statuses if status in {"stale", "unreachable"})
    starting_services = sum(1 for status in service_statuses if status in {"starting", "unknown"})

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
    if runs_disabled_dashboard and configured_service_total > 0:
        print(f"{bold}{cyan}Configured Services:{reset}")
        print(
            f"{dim}services: {configured_service_total} configured | {running_services} running | "
            f"{configured_service_total - running_services} not running | {issue_services} issues{reset}"
        )
    else:
        print(f"{bold}{cyan}Running Services:{reset}")
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
        if state.services or "backend" in configured_service_types:
            self._print_dashboard_service_row(
                label="Backend",
                service=backend_service,
                url=str(backend_url) if backend_url else None,
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
        if state.services or "frontend" in configured_service_types:
            self._print_dashboard_service_row(
                label="Frontend",
                service=frontend_service,
                url=str(frontend_url) if frontend_url else None,
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


def _print_dashboard_service_row(
    self: Any,
    *,
    label: str,
    service: object | None,
    url: str | None,
    configured_not_running: bool,
    ok_color: str,
    warn_color: str,
    bad_color: str,
    label_color: str,
    dim: str,
    reset: str,
) -> None:
    if configured_not_running:
        label_text = f"{label_color}{label}{reset}"
        print(f"    {dim}○{reset} {label_text}: {dim}not running{reset} {dim}[Configured]{reset}")
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
        rendered_listener_pids = [str(value) for value in listener_pids if isinstance(value, int) and value > 0]
        if rendered_listener_pids:
            listener_suffix = f" [Listener PID: {','.join(rendered_listener_pids)}]"
    url_text = url or "n/a"
    if not url and status.lower() == "unreachable":
        fallback_port = getattr(service, "actual_port", None) or getattr(service, "requested_port", None)
        if isinstance(fallback_port, int) and fallback_port > 0 and isinstance(pid, int) and pid > 0:
            url_text = f"http://localhost:{fallback_port}"
    label_text = f"{label_color}{label}{reset}"
    print(
        f"    {color}{icon}{reset} {label_text}: {url_text}{pid_suffix}{listener_suffix} {dim}[{status_label}]{reset}"
    )
    log_path = getattr(service, "log_path", None)
    if isinstance(log_path, str) and log_path.strip():
        print(f"      {dim}log:{reset}")
        print(f"      {log_path}")

    requested = getattr(service, "requested_port", None)
    actual = getattr(service, "actual_port", None)
    if isinstance(requested, int) and requested > 0 and isinstance(actual, int) and actual > 0 and requested != actual:
        print(f"      {dim}port: requested {requested} -> actual {actual}{reset}")


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
    for definition in dependency_definitions():
        component = requirements.component(definition.id)
        if not bool(component.get("enabled", False)) or definition.id == "postgres" or definition.id == "redis":
            continue
        port = component.get("final") or component.get("requested")
        runtime_status = str(component.get("runtime_status", "")).strip().lower()
        if runtime_status == "healthy":
            icon = "✓"
            color = ok_color
            status = "Healthy"
            url = f"http://localhost:{port}" if isinstance(port, int) and port > 0 else "n/a"
        elif runtime_status == "simulated":
            icon = "~"
            color = warn_color
            status = "Simulated"
            url = f"http://localhost:{port}" if isinstance(port, int) and port > 0 else "n/a"
        elif runtime_status == "starting":
            icon = "•"
            color = warn_color
            status = "Starting"
            url = f"http://localhost:{port}" if isinstance(port, int) and port > 0 else "n/a"
        elif runtime_status in {"unhealthy", "unreachable"}:
            icon = "!"
            color = bad_color
            status = "Unhealthy" if runtime_status == "unhealthy" else "Unreachable"
            url = "n/a"
        else:
            url = f"http://localhost:{port}" if isinstance(port, int) and port > 0 else "n/a"
            success = bool(component.get("success", False))
            if success:
                if bool(component.get("simulated", False)):
                    icon = "~"
                    color = warn_color
                    status = "Simulated"
                else:
                    icon = "✓"
                    color = ok_color
                    status = "Healthy"
            else:
                failure_count = len(requirements.failures or [])
                icon = "!"
                color = bad_color if failure_count > 0 else warn_color
                status = "Unhealthy" if failure_count > 0 else "Starting"
        print(f"    {color}{icon}{reset} {definition.display_name}: {url} [{status}]")


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
    summary_raw = entry.get("summary_path")
    if not isinstance(summary_raw, str) or not summary_raw.strip():
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
    print(f"      {color}{icon}{reset} tests: {dim}({timestamp}){reset}")
    print(f"      {summary_path}")


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
            executor.submit(_dashboard_project_pr, self, state=state, project=project): project
            for project in projects
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
    raw = state.metadata.get("dashboard_configured_service_types")
    if not isinstance(raw, list):
        return set()
    return {str(service_type).strip().lower() for service_type in raw if str(service_type).strip()}


def _dashboard_configured_service_total(*, projection: dict[str, object], configured_service_types: set[str]) -> int:
    if not projection or not configured_service_types:
        return 0
    return sum(len(configured_service_types) for _project in projection)


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
    if lowered in {"running", "healthy"}:
        return "✓", ok_color, "Running" if lowered == "running" else "Healthy"
    if lowered == "simulated":
        return "~", warn_color, "Simulated"
    if lowered in {"starting", "unknown"}:
        return "•", warn_color, "Starting" if lowered == "starting" else "Unknown"
    if lowered == "stale":
        return "!", bad_color, "Stale"
    if lowered == "unreachable":
        return "!", bad_color, "Unreachable"
    return "!", bad_color, status or "Error"


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
