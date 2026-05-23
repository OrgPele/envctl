from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Mapping, cast

from envctl_engine.actions.project_action_domain import (
    DirtyWorktreeReport,
    probe_dirty_worktree,
)
from envctl_engine.planning.plan_agent.cmux_transport import launch_review_agent_terminal, review_agent_launch_readiness
from envctl_engine.runtime.command_router import Route, parse_route
from envctl_engine.runtime.command_policy import DASHBOARD_ALWAYS_HIDDEN_COMMANDS
from envctl_engine.state.models import RunState
from envctl_engine.startup.startup_selection_support import (
    _tree_preselected_projects_from_state as _tree_preselected_projects_from_state_impl,
)
from envctl_engine.ui.command_parsing import (
    parse_interactive_command,
    recover_single_letter_command_from_escape_fragment,
    sanitize_interactive_input,
    tokens_set_mode,
)
from envctl_engine.ui.command_aliases import normalize_interactive_command
from envctl_engine.ui.debug_anomaly_rules import detect_dispatch_anomaly
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
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI
from envctl_engine.ui.textual.screens.selector import _run_selector_with_impl
from envctl_engine.ui.textual.screens.text_input_dialog import run_text_input_dialog_textual


DirtyPrDecision = Literal["commit", "skip", "cancel"]
_REVIEW_TAB_OPEN_TOKEN = "__REVIEW_TAB_OPEN__"
_REVIEW_TAB_SKIP_TOKEN = "__REVIEW_TAB_SKIP__"
_REVIEW_TAB_LAUNCH_FLAG = "dashboard_review_tab_launch"
_RETURN_TO_DASHBOARD_PROMPT = "Press Enter to return to dashboard (manual confirmation required): "
_PAUSE_BEFORE_DASHBOARD_COMMANDS = {"test", "review", "logs", "errors", "health", "clear-logs"}

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
        runtime_any = cast(Any, rt)
        """Process a single interactive command."""
        raw_input = raw
        raw = self._sanitize_interactive_input(raw)
        recovered_command = self._recover_single_letter_command_from_escape_fragment(raw_input)
        if not raw and not recovered_command:
            return True, state

        command_tokens = self._parse_interactive_command(raw)
        if command_tokens is None:
            return True, state
        if not command_tokens:
            if recovered_command:
                command_tokens = [recovered_command]
            else:
                return True, state

        if not command_tokens:
            return True, state

        command = command_tokens[0]
        if recovered_command:
            command = recovered_command
            command_tokens[0] = recovered_command
        if command in {"q", "quit", "exit"}:
            return False, state
        if command in {"help", "?"}:
            return True, state
        if command in {"session", "sessions"}:
            print("AI sessions are shown inline under each worktree. Use 'k' to kill AI sessions.")
            return True, state
        if command in {"k", "kill", "kill-session", "kill-sessions"}:
            self._dispatch_kill_session(runtime_any)
            return True, state

        normalized = normalize_interactive_command(command)
        command_tokens[0] = normalized

        try:
            route = parse_route(command_tokens, env={**runtime_any.config.raw, **runtime_any.env})
        except Exception as exc:
            runtime_any._emit(
                "ui.command.parse.failed",
                component="dashboard_orchestrator",
                error=str(exc),
                raw=raw,
            )
            anomaly = detect_dispatch_anomaly(parse_failed=True, raw=raw, sanitized=raw)
            if anomaly is not None:
                runtime_any._emit(anomaly["event"], component="dashboard_orchestrator", **anomaly)
            print(f"Invalid command: {exc}")
            return True, state

        if not self._tokens_set_mode(command_tokens):
            route = Route(
                command=route.command,
                mode=state.mode,
                raw_args=route.raw_args,
                passthrough_args=route.passthrough_args,
                projects=route.projects,
                flags=route.flags,
            )
        if route.command != "blast-all":
            route.flags = {**route.flags, "batch": True, "interactive_command": True}

        route = self._apply_interactive_target_selection(route, state, rt)
        if route is None:
            return True, state

        if route.command == "stop":
            route = self._apply_stop_scope_selection(route, state, rt)
            if route is None:
                return True, state

        if route.command == "pr":
            route = self._dedupe_route_projects_by_git_root(route, state, rt)
            route, state = self._maybe_prepare_pr_commit(route, state, rt)
            if route is None:
                return True, state

        if route.command == "restart":
            route = self._apply_restart_selection(route, state, rt)
            if route is None:
                return True, state

        if route.command == "dashboard":
            runtime_any._print_dashboard_snapshot(state)
            return True, state

        hidden_commands = self._dashboard_hidden_commands(state)
        if route.command in hidden_commands:
            if route.command in DASHBOARD_ALWAYS_HIDDEN_COMMANDS:
                print(f"Command '{route.command}' is not available in this dashboard context.")
                return True, state
            print(
                f"Command '{route.command}' is not available in this dashboard "
                "because envctl runs are disabled for this mode."
            )
            return True, state

        try:
            code = runtime_any.dispatch(route)
        except KeyboardInterrupt:
            code = 2
        runtime_any._emit(
            "ui.command.dispatch.result",
            component="dashboard_orchestrator",
            command=route.command,
            code=code,
        )
        refreshed = runtime_any._try_load_existing_state(mode=state.mode, strict_mode_match=True)
        if code in {2, 130} and refreshed is None:
            refreshed = state
        printed_interactive_result = False
        if route.command == "migrate":
            printed_interactive_result = self._print_project_action_failure_details(
                route,
                state if refreshed is None else refreshed,
            )
        if code not in {0, 2, 130} and not printed_interactive_result:
            self._print_interactive_failure_details(route, state if refreshed is None else refreshed, code=code)
        next_state = refreshed if refreshed is not None else state
        if code == 0 and route.command == "review":
            self._maybe_offer_review_tab_launch(route, next_state, rt)
        if route.command in _PAUSE_BEFORE_DASHBOARD_COMMANDS:
            if bool(getattr(runtime_any, "_dashboard_command_loop_active", False)):
                self._queue_return_to_dashboard_prompt(runtime_any, _RETURN_TO_DASHBOARD_PROMPT)
            else:
                self._read_interactive_line(runtime_any, _RETURN_TO_DASHBOARD_PROMPT)
        if route.command in {"stop-all", "blast-all"}:
            return False, state
        if refreshed is None:
            return False, state
        return True, refreshed

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
        service_lookup = self._stop_services_by_project(state, runtime)
        dependency_lookup = self._stop_dependencies_by_project(state)
        selected_services: set[str] = set()
        selected_dependencies: set[tuple[str, str]] = set()

        for token in values:
            if token.startswith("__STOP__:worktree:"):
                project_name = token.removeprefix("__STOP__:worktree:")
                for service_name, _service_type in service_lookup.get(project_name, []):
                    selected_services.add(service_name)
                for dependency_id, _label in dependency_lookup.get(project_name, []):
                    selected_dependencies.add((project_name, dependency_id))
                continue
            if token.startswith("__STOP__:service:"):
                service_name = token.removeprefix("__STOP__:service:")
                if service_name in state.services:
                    selected_services.add(service_name)
                continue
            if token.startswith("__STOP__:dependency:"):
                _, _, project_name, dependency_id = token.split(":", 3)
                if any(dependency_id == existing_id for existing_id, _label in dependency_lookup.get(project_name, [])):
                    selected_dependencies.add((project_name, dependency_id))

        all_services = set(state.services)
        all_dependencies = {
            (project_name, dependency_id)
            for project_name, dependencies in dependency_lookup.items()
            for dependency_id, _label in dependencies
        }

        flags = {
            key: value
            for key, value in route.flags.items()
            if key
            not in {
                "runtime_scope",
                "backend",
                "frontend",
                "services",
                "stop_dependency_components",
                "stop_preserve_requirements",
            }
        }
        if (
            selected_services
            and selected_services == all_services
            and selected_dependencies == all_dependencies
            and all_dependencies
        ):
            flags["runtime_scope"] = "entire-system"
        else:
            if selected_services:
                flags["services"] = sorted(selected_services)
                flags["stop_preserve_requirements"] = True
            if selected_dependencies:
                flags["stop_dependency_components"] = [
                    f"{project_name}:{dependency_id}"
                    for project_name, dependency_id in sorted(selected_dependencies)
                ]
                flags["stop_preserve_requirements"] = True
        route.flags = flags

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
        runtime_any = cast(Any, rt)
        selected_route = self._apply_project_target_selection(route, state, rt)
        if selected_route is None:
            return None
        route = selected_route
        if isinstance(route.flags.get("commit_message"), str) and str(route.flags.get("commit_message")).strip():
            return route
        if (
            isinstance(route.flags.get("commit_message_file"), str)
            and str(route.flags.get("commit_message_file")).strip()
        ):
            return route
        raw = self._prompt_commit_message(
            runtime_any,
        )
        if raw is None:
            print(self._no_target_selected_message(route.command))
            return None
        message = str(raw).strip()
        if not message:
            return route
        route.flags = {
            **{key: value for key, value in route.flags.items() if key != "commit_message_file"},
            "commit_message": message,
        }
        runtime_any._emit(
            "dashboard.commit_message.selected",
            command="commit",
            explicit=True,
            length=len(message),
        )
        return route

    @staticmethod
    def _dashboard_owned_target_selection_commands() -> set[str]:
        # Commands that already have downstream interactive selectors should not
        # be pre-selected here; otherwise the dashboard changes their contract.
        return {
            "test",
            "pr",
            "commit",
            "review",
            "migrate",
            "blast-worktree",
        }

    @staticmethod
    def _dashboard_owned_project_selection_commands() -> set[str]:
        return {"pr", "commit", "review", "migrate", "blast-worktree"}

    @staticmethod
    def _dashboard_hidden_commands(state: RunState) -> set[str]:
        raw = state.metadata.get("dashboard_hidden_commands")
        hidden = (
            {str(command).strip().lower() for command in raw if str(command).strip()}
            if isinstance(raw, list)
            else set()
        )
        hidden.update(DASHBOARD_ALWAYS_HIDDEN_COMMANDS)
        if not state.services:
            hidden.add("migrate")
        return hidden

    def _apply_project_target_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        runtime_any = cast(Any, rt)
        if self._route_has_explicit_target(route, runtime_any):
            return route

        projects = self._project_names_from_state(state, runtime_any)
        single_project = self._single_project_name(projects)
        if single_project:
            route.projects = [single_project]
            runtime_any._emit(
                "dashboard.target_scope.defaulted",
                command=route.command,
                mode=state.mode,
                scope="single_project",
                project_count=1,
                projects=[single_project],
            )
            return route
        selection = runtime_any._select_project_targets(
            prompt=self._interactive_target_prompt(route.command),
            projects=projects,
            allow_all=True,
            allow_untested=False,
            multi=True,
        )
        if selection.cancelled:
            print(self._no_target_selected_message(route.command))
            return None
        if selection.all_selected:
            scoped_projects = [str(getattr(project, "name", "")).strip() for project in projects]
            scoped_projects = [project for project in scoped_projects if project]
            if scoped_projects:
                route.projects = scoped_projects
                route.flags = {key: value for key, value in route.flags.items() if key != "all"}
                runtime_any._emit(
                    "dashboard.target_scope.defaulted",
                    command=route.command,
                    mode=state.mode,
                    scope="run_state_all_selection",
                    project_count=len(scoped_projects),
                    projects=scoped_projects,
                )
                return route
            route.flags = {**route.flags, "all": True}
            return route
        if selection.project_names:
            route.projects = list(selection.project_names)
            return route
        print(self._no_target_selected_message(route.command))
        return None

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
        return target_selection_support.project_names_from_state(state, rt)

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
        reader = getattr(runtime, "_read_interactive_command_line", None)
        if callable(reader):
            return str(reader(prompt))
        env = getattr(runtime, "env", {})
        return str(RuntimeTerminalUI.read_interactive_command_line(prompt, env))

    @staticmethod
    def _queue_return_to_dashboard_prompt(runtime: Any, prompt: str) -> None:
        try:
            setattr(runtime, "_dashboard_return_prompt", str(prompt))
        except Exception:
            return

    @staticmethod
    def _prompt_text_dialog(
        runtime: Any,
        *,
        title: str,
        help_text: str,
        placeholder: str,
        default_button_label: str,
    ) -> str | None:
        dialog = getattr(runtime, "_prompt_text_input", None)
        if callable(dialog):
            result = dialog(
                title=title,
                help_text=help_text,
                placeholder=placeholder,
                initial_value="",
                default_button_label=default_button_label,
            )
            if result is None:
                return None
            return str(result)
        result = run_text_input_dialog_textual(
            title=title,
            help_text=help_text,
            placeholder=placeholder,
            initial_value="",
            default_button_label=default_button_label,
            emit=getattr(runtime, "_emit", None),
        )
        if result is None:
            return None
        return str(result)

    @staticmethod
    def _prompt_commit_message(runtime: Any) -> str | None:
        return DashboardOrchestrator._prompt_text_dialog(
            runtime,
            title="Commit Message",
            help_text="Commit message (leave blank to use the envctl commit log).",
            placeholder="Type a commit message",
            default_button_label="Use envctl commit log",
        )

    @staticmethod
    def _prompt_pr_message(runtime: Any) -> str | None:
        return DashboardOrchestrator._prompt_text_dialog(
            runtime,
            title="PR Message",
            help_text="PR message (leave blank to use MAIN_TASK.md).",
            placeholder="Type a PR message",
            default_button_label="Use MAIN_TASK.md",
        )

    @staticmethod
    def _sanitize_interactive_input(raw: str) -> str:
        return sanitize_interactive_input(raw)

    @staticmethod
    def _repo_root_for_project(project_root: Path) -> Path | None:
        current = Path(project_root).expanduser().resolve(strict=False)
        for candidate in (current, *current.parents):
            if (candidate / ".git").exists() or (candidate / "todo").is_dir():
                return candidate
        return None

    def _dispatch_kill_session(self, runtime_any: Any) -> None:
        try:
            from envctl_engine.runtime.session_management import list_tmux_sessions  # noqa: PLC0415
            from envctl_engine.runtime.session_management import kill_session  # noqa: PLC0415
            sessions = list_tmux_sessions()
            if not sessions:
                print("No active sessions to kill.")
                return
            values = _run_selector_with_impl(
                prompt="Select sessions to kill:",
                options=[
                    SelectorItem(
                        id=f"tmux-session:{session['name']}",
                        label=f"{session['name']} (windows: {session['windows']})",
                        kind="tmux_session",
                        token=session["name"],
                        scope_signature=(f"tmux_session:{session['name']}",),
                        section="AI Sessions",
                    )
                    for session in sessions
                ],
                multi=True,
                emit=getattr(runtime_any, "_emit", None),
            )
            if not values:
                return
            any_failed = False
            for raw_name in values:
                name = str(raw_name).strip()
                if not name:
                    continue
                print(f"Killing: {name}")
                if not kill_session(name):
                    any_failed = True
            if any_failed:
                print("Finished with session kill errors.")
            else:
                print("Done.")
        except Exception as exc:
            print(f"Error: {exc}")

    @staticmethod
    def _recover_single_letter_command_from_escape_fragment(raw: str) -> str:
        return recover_single_letter_command_from_escape_fragment(raw)

    @staticmethod
    def _parse_interactive_command(raw: str) -> list[str] | None:
        return parse_interactive_command(raw)

    @staticmethod
    def _tokens_set_mode(tokens: list[str]) -> bool:
        return tokens_set_mode(tokens)
