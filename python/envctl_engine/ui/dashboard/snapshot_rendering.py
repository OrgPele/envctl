from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard.snapshot_support import build_dashboard_snapshot_model


@dataclass(frozen=True)
class DashboardSnapshotRenderHooks:
    terminal_size: Callable[[], tuple[int, int]]
    palette: Callable[[], Mapping[str, str]]
    truncate_text: Callable[[str, int], str]
    current_session_id: Callable[[], str | None]
    visual_host: Callable[[], str | None]
    reconcile_state_truth: Callable[[RunState], list[str]]
    emit: Callable[..., None]
    project_pr_map: Callable[[RunState, list[str]], Mapping[str, tuple[str, str]]]
    print_service_row: Callable[..., None]
    print_additional_service_rows: Callable[..., None]
    print_ai_session_row: Callable[..., None]
    print_dependency_rows: Callable[..., None]
    print_shared_dependency_rows: Callable[..., None]
    print_tests_row: Callable[..., None]


class DashboardSnapshotPrinter:
    def __init__(self, hooks: DashboardSnapshotRenderHooks) -> None:
        self._hooks = hooks

    def print_snapshot(self, state: RunState) -> None:
        snapshot = build_dashboard_snapshot_model(
            state,
            visual_host=self._hooks.visual_host(),
            reconcile_fn=self._hooks.reconcile_state_truth,
            emit_fn=self._hooks.emit,
        )
        terminal_width, _ = self._hooks.terminal_size()
        project_name_budget = max(20, terminal_width - 4)
        palette = self._hooks.palette()
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

        print(f"{cyan}{separator}{reset}")
        print(f"{bold}{cyan}Development Environment - Interactive Mode{reset}")
        print(f"{cyan}{separator}{reset}")
        session_id_text = str(self._hooks.current_session_id() or "").strip() or "unknown"
        print(f"{dim}run_id: {state.run_id}  session_id: {session_id_text}  mode: {state.mode}{reset}")
        dashboard_banner = state.metadata.get("dashboard_banner")
        if isinstance(dashboard_banner, str) and dashboard_banner.strip():
            print(f"{dim}{dashboard_banner.strip()}{reset}")
        project_prs = self._hooks.project_pr_map(state, list(snapshot.ordered_projects))
        shared_dependency_grouping = snapshot.shared_dependency_grouping
        if snapshot.runs_disabled_dashboard and snapshot.configured_service_total > 0:
            print(f"{bold}{cyan}Configured Services:{reset}")
            print(
                f"{dim}services: {snapshot.configured_service_total} configured | "
                f"{snapshot.running_services} running | "
                f"{snapshot.configured_service_total - snapshot.running_services} not running | "
                f"{snapshot.issue_services} issues{reset}"
            )
        else:
            print(f"{bold}{cyan}Running Services:{reset}")
            if snapshot.stopped_service_count:
                print(
                    f"{dim}services: {snapshot.total_services} total | {snapshot.running_services} running | "
                    f"{snapshot.stopped_service_count} not running | {snapshot.starting_services} starting/unknown | "
                    f"{snapshot.issue_services} issues{reset}"
                )
            else:
                print(
                    f"{dim}services: {snapshot.total_services} total | {snapshot.running_services} running | "
                    f"{snapshot.starting_services} starting/unknown | {snapshot.issue_services} issues{reset}"
                )
        print(f"{cyan}{separator}{reset}")
        project_colors = [blue, magenta, cyan, green, yellow]
        for project_index, project in enumerate(snapshot.ordered_projects):
            item = snapshot.projection.get(project, {})
            if not isinstance(item, dict):
                continue
            self._print_project(
                state=state,
                snapshot=snapshot,
                project=str(project),
                project_item=item,
                project_index=project_index,
                project_pr=project_prs.get(project),
                project_name_budget=project_name_budget,
                project_colors=project_colors,
                colors={
                    "reset": reset,
                    "bold": bold,
                    "cyan": cyan,
                    "green": green,
                    "yellow": yellow,
                    "red": red,
                    "magenta": magenta,
                    "gray": gray,
                    "dim": dim,
                },
                shared_dependency_grouping=shared_dependency_grouping,
            )
        if shared_dependency_grouping:
            self._hooks.print_shared_dependency_rows(
                state=state,
                ok_color=green,
                warn_color=yellow,
                bad_color=red,
                label_color=cyan,
                reset=reset,
            )

    def _print_project(
        self,
        *,
        state: RunState,
        snapshot: Any,
        project: str,
        project_item: dict[Any, Any],
        project_index: int,
        project_pr: tuple[str, str] | None,
        project_name_budget: int,
        project_colors: list[str],
        colors: Mapping[str, str],
        shared_dependency_grouping: bool,
    ) -> None:
        backend_url = project_item.get("backend_url")
        frontend_url = project_item.get("frontend_url")
        backend_service = state.services.get(f"{project} Backend")
        frontend_service = state.services.get(f"{project} Frontend")
        stopped_for_project = snapshot.stopped_services.get(project, {})
        configured_missing_for_project = snapshot.configured_missing_services.get(project, set())
        backend_stopped = backend_service is None and (
            "backend" in stopped_for_project or "backend" in configured_missing_for_project
        )
        frontend_stopped = frontend_service is None and (
            "frontend" in stopped_for_project or "frontend" in configured_missing_for_project
        )
        reset = colors["reset"]
        bold = colors["bold"]
        cyan = colors["cyan"]
        green = colors["green"]
        yellow = colors["yellow"]
        red = colors["red"]
        magenta = colors["magenta"]
        gray = colors["gray"]
        dim = colors["dim"]
        project_display = self._hooks.truncate_text(project, project_name_budget)
        project_color = project_colors[project_index % len(project_colors)]
        if project_pr is not None:
            project_pr_url, project_pr_state = project_pr
            merged_suffix = f" {dim}(merged){reset}" if project_pr_state == "merged" else ""
            print(
                f"  {bold}{project_color}{project_display}{reset} {dim}PR:{reset} "
                f"{gray}{project_pr_url}{reset}{merged_suffix}"
            )
        else:
            print(f"  {bold}{project_color}{project_display}{reset}")
        show_configured_backend = snapshot.runs_disabled_dashboard and "backend" in snapshot.configured_service_types
        if backend_service is not None or backend_stopped or show_configured_backend:
            self._hooks.print_service_row(
                label="Backend",
                service=backend_service,
                url=str(backend_url) if backend_url else None,
                stopped_not_running=backend_stopped,
                configured_not_running=bool(
                    snapshot.runs_disabled_dashboard
                    and backend_service is None
                    and "backend" in snapshot.configured_service_types
                ),
                ok_color=green,
                warn_color=yellow,
                bad_color=red,
                label_color=cyan,
                dim=dim,
                reset=reset,
            )
        show_configured_frontend = snapshot.runs_disabled_dashboard and "frontend" in snapshot.configured_service_types
        if frontend_service is not None or frontend_stopped or show_configured_frontend:
            self._hooks.print_service_row(
                label="Frontend",
                service=frontend_service,
                url=str(frontend_url) if frontend_url else None,
                stopped_not_running=frontend_stopped,
                configured_not_running=bool(
                    snapshot.runs_disabled_dashboard
                    and frontend_service is None
                    and "frontend" in snapshot.configured_service_types
                ),
                ok_color=green,
                warn_color=yellow,
                bad_color=red,
                label_color=magenta,
                dim=dim,
                reset=reset,
            )
        self._hooks.print_additional_service_rows(
            project=project,
            project_item=project_item,
            state=state,
            stopped_for_project=stopped_for_project,
            configured_missing_for_project=configured_missing_for_project,
            runs_disabled_dashboard=snapshot.runs_disabled_dashboard,
            configured_service_types=snapshot.configured_service_types,
            ok_color=green,
            warn_color=yellow,
            bad_color=red,
            label_color=cyan,
            dim=dim,
            reset=reset,
        )
        self._hooks.print_ai_session_row(
            state=state,
            project=project,
            gray=gray,
            dim=dim,
            reset=reset,
            render_launch_fallback=snapshot.runs_disabled_dashboard or state.mode == "trees",
        )
        if not shared_dependency_grouping:
            self._hooks.print_dependency_rows(
                state=state,
                project=project,
                ok_color=green,
                warn_color=yellow,
                bad_color=red,
                label_color=cyan,
                reset=reset,
            )
        self._hooks.print_tests_row(
            state=state,
            project=project,
            ok_color=green,
            bad_color=red,
            dim=dim,
            reset=reset,
        )
        print("")
