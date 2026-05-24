from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping, cast

from envctl_engine.actions.project_action_domain import (
    DirtyWorktreeReport,
    probe_dirty_worktree,
)
from envctl_engine.planning.plan_agent.cmux_transport import launch_review_agent_terminal, review_agent_launch_readiness
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.startup.startup_selection_support import (
    _tree_preselected_projects_from_state as _tree_preselected_projects_from_state_impl,
)
import envctl_engine.ui.dashboard.command_support as command_support
from envctl_engine.ui.dashboard import project_target_support
from envctl_engine.ui.dashboard import pr_and_target_support
from envctl_engine.ui.dashboard import target_selection_support
from envctl_engine.ui.dashboard.failure_detail_support import (
    ensure_short_test_summary_path,
    print_interactive_failure_details,
    print_project_action_failure_details,
    print_test_failure_details,
    print_migrate_result_details,
    failure_details_available,
    summary_display_path,
)
from envctl_engine.ui.dashboard.stop_scope_support import (
    apply_stop_scope_selection,
    apply_stop_resource_tokens,
    stop_resource_items,
    stop_project_order,
    stop_services_by_project,
    stop_dependencies_by_project,
    stop_service_type,
    stop_service_detail,
    stop_route_has_explicit_scope,
)
from envctl_engine.ui.dashboard.restart_selection_support import (
    apply_restart_selection,
    apply_restart_resource_selection,
    restart_resource_items,
    apply_restart_resource_tokens,
    has_dashboard_stopped_services,
    has_restartable_inactive_services,
    restart_project_order,
    restart_services_by_project,
    dashboard_stopped_services_by_project,
    dashboard_project_configured_services,
    dashboard_configured_missing_services_by_project,
)
from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.dashboard_loop_support import run_legacy_dashboard_loop
from envctl_engine.ui.textual.screens.selector import _run_selector_with_impl


DirtyPrDecision = Literal["commit", "skip", "cancel"]
_REVIEW_TAB_OPEN_TOKEN = "__REVIEW_TAB_OPEN__"
_REVIEW_TAB_SKIP_TOKEN = "__REVIEW_TAB_SKIP__"
_REVIEW_TAB_LAUNCH_FLAG = "dashboard_review_tab_launch"

_DASHBOARD_PR_COMPAT_SYMBOLS = (
    probe_dirty_worktree,
    launch_review_agent_terminal,
    review_agent_launch_readiness,
)


class DashboardOrchestrator:
    def __init__(self, runtime: Any) -> None:
        self.runtime = runtime

    def execute(self, route: Route) -> int:
        rt: Any = self.runtime
        state = rt._try_load_existing_state(  # type: ignore[attr-defined]
            mode=route.mode,
            strict_mode_match=rt._state_lookup_strict_mode_match(route),  # type: ignore[attr-defined]
        )
        if state is None:
            rt._emit("dashboard.snapshot.source", reason="reload-failed", mode=route.mode)  # type: ignore[attr-defined]
            print("No active run state found.")
            return 0
        rt._emit("dashboard.snapshot.source", reason="fresh-load", mode=state.mode, run_id=state.run_id)  # type: ignore[attr-defined]
        if rt.config.runtime_truth_mode == "strict" and rt._state_has_synthetic_services(state):  # type: ignore[attr-defined]
            rt._emit(  # type: ignore[attr-defined]
                "synthetic.execution.blocked",
                command="dashboard",
                reason_code="synthetic_state_detected",
            )
            rt._emit(  # type: ignore[attr-defined]
                "cutover.gate.fail_reason",
                gate="command_parity",
                reason="synthetic_state_detected",
                scope="dashboard",
            )
            print("Dashboard blocked: synthetic placeholder defaults detected.")
            return 1
        if rt._should_enter_dashboard_interactive(route):  # type: ignore[attr-defined]
            interactive_runner = getattr(rt, "_run_interactive_dashboard_loop", None)
            if callable(interactive_runner):
                return cast(int, interactive_runner(state))
            return self.run_interactive_dashboard_loop(state, rt)
        if bool(route.flags.get("interactive")) or bool(route.flags.get("dashboard_interactive")):
            print("Interactive dashboard requires a TTY; showing snapshot.")
        rt._print_dashboard_snapshot(state)  # type: ignore[attr-defined]
        return 0

    def run_interactive_dashboard_loop(self, state: RunState, rt: object) -> int:
        runtime_any = cast(Any, rt)
        return run_legacy_dashboard_loop(
            state=state,
            runtime=runtime_any,
            fallback_handler=self._run_interactive_command,
            sanitize=self._sanitize_interactive_input,
        )

    def _run_interactive_command(self, raw: str, state: RunState, rt: object) -> tuple[bool, RunState]:
        return command_support.run_interactive_command(self, raw, state, rt)

    def _print_interactive_failure_details(self, route: Route, state: RunState, *, code: int) -> None:
        print_interactive_failure_details(
            route=route,
            state=state,
            code=code,
            runtime=self.runtime,
            test_failure_details_available_fn=self._failure_details_available,
            print_test_failure_details_fn=self._print_test_failure_details,
            print_project_action_failure_details_fn=self._print_project_action_failure_details,
        )

    def _failure_details_available(self, route: Route, state: RunState) -> bool:
        return failure_details_available(
            route,
            state,
            project_names_from_state_fn=lambda s: self._project_names_from_state(s, cast(Any, self.runtime)),
        )

    def _print_test_failure_details(self, route: Route, state: RunState) -> bool:
        return print_test_failure_details(
            route, state, runtime=self.runtime,
            project_names_from_state_fn=lambda s: self._project_names_from_state(s, cast(Any, self.runtime))
        )

    @staticmethod
    def _summary_display_path(*, project_name: str, entry: dict[str, object]) -> str:
        return summary_display_path(project_name=project_name, entry=entry)

    @staticmethod
    def _ensure_short_test_summary_path(*, project_name: str, summary_path: str) -> str:
        return ensure_short_test_summary_path(project_name=project_name, summary_path=summary_path)

    def _print_project_action_failure_details(self, route: Route, state: RunState) -> bool:
        return print_project_action_failure_details(
            route, state, runtime=self.runtime,
            project_names_from_state_fn=lambda s: self._project_names_from_state(s, cast(Any, self.runtime)),
            project_name_list_fn=self._project_name_list,
        )

    def _print_migrate_result_details(self, route: Route, state: RunState) -> bool:
        return print_migrate_result_details(
            route, state, runtime=self.runtime,
            project_names_from_state_fn=lambda s: self._project_names_from_state(s, cast(Any, self.runtime)),
            project_name_list_fn=self._project_name_list,
        )

    def _apply_interactive_target_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        if route.command == "restart":
            return route
        if route.command == "pr":
            return self._apply_pr_selection(route, state, rt)
        if route.command == "commit":
            return self._apply_commit_selection(route, state, rt)
        if route.command not in self._dashboard_owned_target_selection_commands():
            return route

        if route.command in self._dashboard_owned_project_selection_commands():
            selected_route = self._apply_project_target_selection(route, state, rt)
            if selected_route is None:
                return None
            if selected_route.command == "review":
                return self._apply_review_tab_launch_selection(selected_route, state, rt)
            return selected_route

        runtime_any = cast(Any, rt)
        if self._route_has_explicit_target(route, runtime_any):
            return route

        projects = self._project_names_from_state(state, runtime_any)
        selected_projects = self._select_dashboard_projects(
            command=route.command,
            state=state,
            projects=projects,
            runtime=runtime_any,
        )
        if selected_projects is None:
            print(self._no_target_selected_message(route.command))
            return None
        route.projects = list(selected_projects)

        selected_service_types = self._select_dashboard_service_types(
            command=route.command,
            state=state,
            selected_projects=selected_projects,
            runtime=runtime_any,
        )
        if selected_service_types is None:
            print(self._no_target_selected_message(route.command))
            return None

        if route.command == "test":
            route.flags = {
                key: value
                for key, value in route.flags.items()
                if key not in {"backend", "frontend", "services", "failed"}
            }
            if any(service_type == "failed" for service_type in selected_service_types):
                route.flags["failed"] = True
                return route
            selected_service_names = self._service_names_for_projects_and_types(
                state,
                runtime_any,
                project_names=selected_projects,
                service_types=selected_service_types,
            )
            if selected_service_names:
                route.flags["services"] = selected_service_names
            selected_types = set(selected_service_types)
            if selected_types == {"backend"}:
                route.flags = {**route.flags, "backend": True, "frontend": False}
            elif selected_types == {"frontend"}:
                route.flags = {**route.flags, "backend": False, "frontend": True}
            return route

        return route

    def _apply_stop_scope_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        return apply_stop_scope_selection(
            route, state, cast(Any, rt),
            stop_resource_items_fn=self._stop_resource_items,
            apply_stop_resource_tokens_fn=self._apply_stop_resource_tokens,
            selector_fn=_run_selector_with_impl,
        )

    @staticmethod
    def _stop_route_has_explicit_scope(route: Route, runtime: Any) -> bool:
        return stop_route_has_explicit_scope(route, runtime)

    def _stop_resource_items(self, state: RunState, runtime: Any) -> list[SelectorItem]:
        return stop_resource_items(
            state, runtime,
            project_names_from_state_fn=self._project_names_from_state,
            stop_project_order_fn=self._stop_project_order,
            stop_services_by_project_fn=self._stop_services_by_project,
            stop_dependencies_by_project_fn=self._stop_dependencies_by_project,
            stop_service_detail_fn=self._stop_service_detail,
        )

    def _apply_stop_resource_tokens(self, route: Route, state: RunState, runtime: Any, values: list[str]) -> None:
        apply_stop_resource_tokens(route, state, runtime, values)

    def _stop_project_order(self, state: RunState, runtime: Any) -> list[str]:
        return stop_project_order(state, runtime, project_names_from_state_fn=self._project_names_from_state)

    @staticmethod
    def _stop_services_by_project(state: RunState, runtime: Any) -> dict[str, list[tuple[str, str]]]:
        return stop_services_by_project(state, runtime)

    @staticmethod
    def _stop_dependencies_by_project(state: RunState) -> dict[str, list[tuple[str, str]]]:
        return stop_dependencies_by_project(state)

    @staticmethod
    def _stop_service_type(service_name: str, service: object) -> str:
        return stop_service_type(service_name, service)

    @staticmethod
    def _stop_service_detail(service_name: str, service_type: str) -> str:
        return stop_service_detail(service_name, service_type)

    def _apply_commit_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        return project_target_support.apply_commit_selection(self, route, state, rt)

    @staticmethod
    def _dashboard_owned_target_selection_commands() -> set[str]:
        return project_target_support.dashboard_owned_target_selection_commands()

    @staticmethod
    def _dashboard_owned_project_selection_commands() -> set[str]:
        return project_target_support.dashboard_owned_project_selection_commands()

    @staticmethod
    def _dashboard_hidden_commands(state: RunState) -> set[str]:
        raw = state.metadata.get("dashboard_hidden_commands")
        hidden = (
            {str(command).strip().lower() for command in raw if str(command).strip()}
            if isinstance(raw, list)
            else set()
        )
        hidden.update(command_support.DASHBOARD_ALWAYS_HIDDEN_COMMANDS)
        if not state.services:
            hidden.add("migrate")
        return hidden

    def _apply_project_target_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        return project_target_support.apply_project_target_selection(self, route, state, rt)

    def _apply_pr_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        return pr_and_target_support.apply_pr_selection(self, route, state, rt)

    def _maybe_prepare_pr_commit(self, route: Route, state: RunState, rt: object) -> tuple[Route | None, RunState]:
        return pr_and_target_support.maybe_prepare_pr_commit(self, route, state, rt)

    def _dirty_pr_reports(self, route: Route, state: RunState, runtime: Any) -> list[DirtyWorktreeReport]:
        pr_and_target_support.probe_dirty_worktree = probe_dirty_worktree
        return pr_and_target_support.dirty_pr_reports(self, route, state, runtime)

    def _dedupe_route_projects_by_git_root(self, route: Route, state: RunState, rt: object) -> Route:
        return pr_and_target_support.dedupe_route_projects_by_git_root(self, route, state, rt)

    @staticmethod
    def _repo_root(runtime: Any) -> Path:
        return pr_and_target_support.repo_root_from_runtime(runtime)

    def _project_roots_for_route(self, route: Route, state: RunState, runtime: Any) -> dict[str, Path]:
        return pr_and_target_support.project_roots_for_route(self, route, state, runtime)

    def _maybe_offer_review_tab_launch(self, route: Route, state: RunState, rt: object) -> None:
        pr_and_target_support.launch_review_agent_terminal = launch_review_agent_terminal
        pr_and_target_support.maybe_offer_review_tab_launch(self, route, state, rt)

    def _apply_review_tab_launch_selection(self, route: Route, state: RunState, rt: object) -> Route:
        pr_and_target_support.review_agent_launch_readiness = review_agent_launch_readiness
        return pr_and_target_support.apply_review_tab_launch_selection(self, route, state, rt)

    def _review_tab_target(self, route: Route, state: RunState, runtime: Any) -> tuple[str, Path] | None:
        return pr_and_target_support.review_tab_target(self, route, state, runtime)

    @staticmethod
    def _review_tab_unavailable_message(reason: str, missing: tuple[str, ...]) -> str:
        return pr_and_target_support.review_tab_unavailable_message(reason, missing)

    @staticmethod
    def _review_bundle_path(state: RunState, *, project_name: str) -> Path | None:
        return pr_and_target_support.review_bundle_path(state, project_name=project_name)

    @staticmethod
    def _dirty_pr_prompt(dirty_targets: list[DirtyWorktreeReport]) -> str:
        return pr_and_target_support.dirty_pr_prompt(dirty_targets)

    @staticmethod
    def _prompt_review_tab_menu(runtime: Any, *, project_name: str) -> DirtyPrDecision:
        pr_and_target_support._run_selector_with_impl = _run_selector_with_impl
        return pr_and_target_support.prompt_review_tab_menu(runtime, project_name=project_name)

    @staticmethod
    def _dirty_categories(report: DirtyWorktreeReport) -> list[str]:
        return pr_and_target_support.dirty_categories(report)

    @staticmethod
    def _prompt_dirty_pr_menu(runtime: Any, *, title: str, prompt: str) -> DirtyPrDecision:
        pr_and_target_support._run_selector_with_impl = _run_selector_with_impl
        return pr_and_target_support.prompt_dirty_pr_menu(runtime, title=title, prompt=prompt)

    @staticmethod
    def _prompt_yes_no_dialog(runtime: Any, *, title: str, prompt: str) -> DirtyPrDecision:
        return pr_and_target_support.prompt_yes_no_dialog(runtime, title=title, prompt=prompt)

    def _default_pr_base_branch(self, runtime: Any) -> str:
        return pr_and_target_support.default_pr_base_branch(self, runtime)

    def _pr_base_branch_options(self, runtime: Any, *, default_branch: str) -> list[SelectorItem]:
        return pr_and_target_support.pr_base_branch_options(self, runtime, default_branch=default_branch)

    def _pr_git_root(self, runtime: Any) -> Path:
        return pr_and_target_support.pr_git_root(self, runtime)

    def _run_pr_selection_flow(
        self,
        *,
        projects: list[object],
        initial_project_names: tuple[str, ...] | list[str],
        default_branch: str,
        runtime: Any,
    ):
        return pr_and_target_support.run_pr_selection_flow(
            self,
            projects=projects,
            initial_project_names=initial_project_names,
            default_branch=default_branch,
            runtime=runtime,
        )

    @staticmethod
    def _single_project_name(projects: list[object]) -> str:
        return pr_and_target_support.single_project_name(projects)

    @staticmethod
    def _interactive_target_prompt(command: str) -> str:
        return pr_and_target_support.interactive_target_prompt(command)

    @staticmethod
    def _no_target_selected_message(command: str) -> str:
        return pr_and_target_support.no_target_selected_message(command)

    def _apply_restart_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        runtime_any = cast(Any, rt)
        return apply_restart_selection(
            route, state, runtime_any,
            has_restartable_inactive_services_fn=self._has_restartable_inactive_services,
            stop_dependencies_by_project_fn=self._stop_dependencies_by_project,
            apply_restart_resource_selection_fn=self._apply_restart_resource_selection,
            select_dashboard_projects_fn=self._select_dashboard_projects,
            select_dashboard_service_types_fn=self._select_dashboard_service_types,
            service_names_for_projects_and_types_fn=self._service_names_for_projects_and_types,
            project_names_from_state_fn=self._project_names_from_state,
            project_name_list_fn=self._project_name_list,
            available_service_types_for_projects_fn=self._available_service_types_for_projects,
        )

    def _apply_restart_resource_selection(self, route: Route, state: RunState, runtime: Any) -> Route | None:
        return apply_restart_resource_selection(
            route, state, runtime,
            restart_resource_items_fn=self._restart_resource_items,
            apply_restart_resource_tokens_fn=self._apply_restart_resource_tokens,
            selector_fn=_run_selector_with_impl,
        )

    def _restart_resource_items(self, state: RunState, runtime: Any) -> list[SelectorItem]:
        return restart_resource_items(
            state, runtime,
            restart_project_order_fn=self._restart_project_order,
            restart_services_by_project_fn=self._restart_services_by_project,
            stop_dependencies_by_project_fn=self._stop_dependencies_by_project,
            stop_service_detail_fn=self._stop_service_detail,
        )

    def _apply_restart_resource_tokens(self, route: Route, state: RunState, runtime: Any, values: list[str]) -> None:
        apply_restart_resource_tokens(route, state, runtime, values)

    @staticmethod
    def _has_dashboard_stopped_services(state: RunState) -> bool:
        return has_dashboard_stopped_services(
            state,
            dashboard_stopped_services_by_project_fn=dashboard_stopped_services_by_project,
        )

    @staticmethod
    def _has_restartable_inactive_services(state: RunState) -> bool:
        return has_restartable_inactive_services(
            state,
            dashboard_stopped_services_by_project_fn=dashboard_stopped_services_by_project,
            dashboard_configured_missing_services_by_project_fn=dashboard_configured_missing_services_by_project,
        )

    def _restart_project_order(self, state: RunState, runtime: Any) -> list[str]:
        return restart_project_order(
            state, runtime,
            stop_project_order_fn=self._stop_project_order,
            dashboard_stopped_services_by_project_fn=self._dashboard_stopped_services_by_project,
            dashboard_project_configured_services_fn=self._dashboard_project_configured_services,
        )

    def _restart_services_by_project(self, state: RunState, runtime: Any) -> dict[str, list[tuple[str, str, bool]]]:
        return restart_services_by_project(state, runtime)

    @staticmethod
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
            if not project or service_type not in {"backend", "frontend"}:
                continue
            stopped.setdefault(project, {})[service_type] = name or f"{project} {service_type.title()}"
        return stopped

    @staticmethod
    def _dashboard_project_configured_services(state: RunState) -> dict[str, set[str]]:
        return dashboard_project_configured_services(state)

    @staticmethod
    def _dashboard_configured_missing_services_by_project(state: RunState) -> dict[str, set[str]]:
        return dashboard_configured_missing_services_by_project(state)

    def _default_interactive_targets(self, route: Route, state: RunState, rt: object) -> Route:
        return target_selection_support.default_interactive_targets(route, state, rt)

    @staticmethod
    def _route_has_explicit_target(route: Route, runtime: object) -> bool:
        return target_selection_support.route_has_explicit_target(route, runtime)

    @staticmethod
    def _restart_service_types_from_service_names(service_names: list[str]) -> list[str]:
        return target_selection_support.restart_service_types_from_service_names(service_names)

    @staticmethod
    def _service_types_from_service_names(service_names: list[str]) -> set[str]:
        return target_selection_support.service_types_from_service_names(service_names)

    @staticmethod
    def _project_names_from_state(state: RunState, rt: object) -> list[object]:
        return target_selection_support.dashboard_project_names_from_state(state, rt)

    @staticmethod
    def _project_name_list(projects: list[object]) -> list[str]:
        return target_selection_support.project_name_list(projects)

    def _select_dashboard_projects(
        self,
        *,
        command: str,
        state: RunState,
        projects: list[object],
        runtime: Any,
    ) -> list[str] | None:
        return target_selection_support.select_dashboard_projects(
            self,
            command=command,
            state=state,
            projects=projects,
            runtime=runtime,
        )

    @staticmethod
    def _dashboard_preselected_projects(
        *,
        state: RunState,
        projects: list[object],
        runtime: Any,
    ) -> list[str]:
        target_selection_support._tree_preselected_projects_from_state_impl = (
            _tree_preselected_projects_from_state_impl
        )
        return target_selection_support.dashboard_preselected_projects(
            state=state,
            projects=projects,
            runtime=runtime,
        )

    def _select_dashboard_service_types(
        self,
        *,
        command: str,
        state: RunState,
        selected_projects: list[str],
        runtime: Any,
    ) -> list[str] | None:
        return target_selection_support.select_dashboard_service_types(
            self,
            command=command,
            state=state,
            selected_projects=selected_projects,
            runtime=runtime,
        )

    def _select_dashboard_test_scope(
        self,
        *,
        state: RunState,
        selected_projects: list[str],
        runtime: Any,
    ) -> list[str] | None:
        return target_selection_support.select_dashboard_test_scope(
            self,
            state=state,
            selected_projects=selected_projects,
            runtime=runtime,
        )

    @staticmethod
    def _all_tests_scope_available(
        state: RunState,
        runtime: Any,
        *,
        project_names: list[str],
    ) -> bool:
        return target_selection_support.all_tests_scope_available(state, runtime, project_names=project_names)

    @staticmethod
    def _failed_test_scope_available(state: RunState, *, project_names: list[str]) -> bool:
        return target_selection_support.failed_test_scope_available(state, project_names=project_names)

    @staticmethod
    def _available_service_types_for_projects(
        state: RunState,
        runtime: Any,
        *,
        project_names: list[str],
    ) -> list[str]:
        return target_selection_support.available_service_types_for_projects(
            state,
            runtime,
            project_names=project_names,
        )

    @staticmethod
    def _service_names_for_projects_and_types(
        state: RunState,
        runtime: Any,
        *,
        project_names: list[str],
        service_types: list[str],
    ) -> list[str]:
        return target_selection_support.service_names_for_projects_and_types(
            state,
            runtime,
            project_names=project_names,
            service_types=service_types,
        )

    @staticmethod
    def _worktree_prompt(command: str) -> str:
        return target_selection_support.worktree_prompt(command)

    @staticmethod
    def _service_prompt(command: str) -> str:
        return target_selection_support.service_prompt(command)

    @staticmethod
    def _read_interactive_line(runtime: Any, prompt: str) -> str:
        return command_support.read_interactive_line(runtime, prompt)

    @staticmethod
    def _queue_return_to_dashboard_prompt(runtime: Any, prompt: str) -> None:
        command_support.queue_return_to_dashboard_prompt(runtime, prompt)

    @staticmethod
    def _prompt_text_dialog(
        runtime: Any,
        *,
        title: str,
        help_text: str,
        placeholder: str,
        default_button_label: str,
    ) -> str | None:
        return command_support.prompt_text_dialog(
            runtime,
            title=title,
            help_text=help_text,
            placeholder=placeholder,
            default_button_label=default_button_label,
        )

    @staticmethod
    def _prompt_commit_message(runtime: Any) -> str | None:
        return command_support.prompt_commit_message(runtime)

    @staticmethod
    def _prompt_pr_message(runtime: Any) -> str | None:
        return command_support.prompt_pr_message(runtime)

    @staticmethod
    def _sanitize_interactive_input(raw: str) -> str:
        return command_support.sanitize_interactive_input(raw)

    @staticmethod
    def _repo_root_for_project(project_root: Path) -> Path | None:
        return command_support.repo_root_for_project(project_root)

    def _dispatch_kill_session(self, runtime_any: Any) -> None:
        command_support.dispatch_kill_session(runtime_any, selector_fn=_run_selector_with_impl)

    @staticmethod
    def _recover_single_letter_command_from_escape_fragment(raw: str) -> str:
        return command_support.recover_single_letter_command_from_escape_fragment(raw)

    @staticmethod
    def _parse_interactive_command(raw: str) -> list[str] | None:
        return command_support.parse_interactive_command(raw)

    @staticmethod
    def _tokens_set_mode(tokens: list[str]) -> bool:
        return command_support.tokens_set_mode(tokens)
