from __future__ import annotations

from contextlib import suppress
import hashlib
from pathlib import Path
import subprocess
import sys
from typing import Any, Literal, cast

from envctl_engine.actions.action_command_orchestrator import ActionCommandOrchestrator
from envctl_engine.actions.actions_test import default_test_commands
from envctl_engine.actions.project_action_domain import DirtyWorktreeReport, detect_default_branch, probe_dirty_worktree, resolve_git_root
from envctl_engine.planning.plan_agent_launch_support import launch_review_agent_terminal, review_agent_launch_readiness
from envctl_engine.runtime.command_router import Route, parse_route
from envctl_engine.runtime.command_policy import DASHBOARD_ALWAYS_HIDDEN_COMMANDS
from envctl_engine.state.models import RunState
from envctl_engine.startup.startup_selection_support import (
    _tree_preselected_projects_from_state as _tree_preselected_projects_from_state_impl,
)
from envctl_engine.shared.services import project_name_from_service_name
from envctl_engine.test_output.failure_summary import summary_excerpt_from_entry
from envctl_engine.ui.command_parsing import (
    parse_interactive_command,
    recover_single_letter_command_from_escape_fragment,
    sanitize_interactive_input,
    tokens_set_mode,
)
from envctl_engine.ui.command_aliases import normalize_interactive_command
from envctl_engine.ui.debug_anomaly_rules import detect_dispatch_anomaly
from envctl_engine.ui.dashboard.pr_flow import run_pr_flow
from envctl_engine.ui.selector_model import SelectorItem
from envctl_engine.ui.dashboard_loop_support import run_legacy_dashboard_loop
from envctl_engine.ui.path_links import render_path_for_terminal
from envctl_engine.ui.selection_support import (
    no_target_selected_message,
    project_names_from_state,
    route_has_explicit_target,
    service_types_from_service_names,
)
from envctl_engine.ui.selection_support import SimpleProject
from envctl_engine.ui.dashboard.terminal_ui import RuntimeTerminalUI
from envctl_engine.ui.textual.screens.selector import _run_selector_with_impl
from envctl_engine.ui.textual.screens.text_input_dialog import run_text_input_dialog_textual


DirtyPrDecision = Literal["commit", "skip", "cancel"]
_REVIEW_TAB_OPEN_TOKEN = "__REVIEW_TAB_OPEN__"
_REVIEW_TAB_SKIP_TOKEN = "__REVIEW_TAB_SKIP__"
_REVIEW_TAB_LAUNCH_FLAG = "dashboard_review_tab_launch"


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
        raw = self._sanitize_interactive_input(raw)
        if not raw:
            return True, state

        command_tokens = self._parse_interactive_command(raw)
        if command_tokens is None:
            return True, state
        if not command_tokens:
            return True, state

        command = command_tokens[0]
        if command in {"q", "quit", "exit"}:
            return False, state
        if command in {"help", "?"}:
            return True, state
        if command in {"s", "session"}:
            self._dispatch_session_command(runtime_any)
            return True, state
        if command in {"a", "ai-attach", "session-attach"}:
            self._dispatch_session_attach(runtime_any)
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
        if route.command == "test":
            if bool(getattr(runtime_any, "_dashboard_command_loop_active", False)):
                self._queue_return_to_dashboard_prompt(runtime_any, "Press Enter to return to dashboard: ")
            else:
                self._read_interactive_line(runtime_any, "Press Enter to return to dashboard: ")
        if route.command in {"stop-all", "blast-all"}:
            return False, state
        if refreshed is None:
            return False, state
        return True, refreshed

    def _print_interactive_failure_details(self, route: Route, state: RunState, *, code: int) -> None:
        if route.command == "test":
            if bool(route.flags.get("interactive_command")) and self._test_failure_details_available(route, state):
                return
            printed = self._print_test_failure_details(route, state)
            if printed:
                return
        printed = self._print_project_action_failure_details(route, state)
        if printed:
            return
        print(f"Command failed (exit {code}).")

    def _test_failure_details_available(self, route: Route, state: RunState) -> bool:
        metadata = state.metadata.get("project_test_summaries")
        if not isinstance(metadata, dict):
            return False
        project_names = route.projects or self._project_names_from_state(state, cast(Any, self.runtime))
        for project_name_raw in project_names:
            project_name = str(project_name_raw).strip()
            entry = metadata.get(project_name)
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("status", "")).strip().lower()
            if status and status != "failed":
                continue
            if self._test_summary_display_path(project_name=project_name, entry=entry):
                return True
            if summary_excerpt_from_entry(entry, max_lines=3):
                return True
        return False

    def _print_test_failure_details(self, route: Route, state: RunState) -> bool:
        metadata = state.metadata.get("project_test_summaries")
        if not isinstance(metadata, dict):
            return False
        project_names = route.projects or self._project_names_from_state(state, cast(Any, self.runtime))
        printed = False
        for project_name_raw in project_names:
            project_name = str(project_name_raw).strip()
            entry = metadata.get(project_name)
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("status", "")).strip().lower()
            if status and status != "failed":
                continue
            summary_path = self._test_summary_display_path(project_name=project_name, entry=entry)
            excerpt_lines = summary_excerpt_from_entry(entry, max_lines=3)
            if not summary_path and not excerpt_lines:
                continue
            print(f"Test failure summary for {project_name}:")
            for line in excerpt_lines:
                print(line)
            if summary_path:
                print(
                    render_path_for_terminal(
                        summary_path,
                        env=getattr(self.runtime, "env", {}),
                        stream=sys.stdout,
                        interactive_tty=True,
                    )
                )
            printed = True
        return printed

    @staticmethod
    def _test_summary_display_path(*, project_name: str, entry: dict[str, object]) -> str:
        short_path = str(entry.get("short_summary_path", "") or "").strip()
        if short_path:
            resolved = DashboardOrchestrator._ensure_short_test_summary_path(
                project_name=project_name,
                summary_path=short_path,
            )
            return resolved or short_path
        summary_path = str(entry.get("summary_path", "") or "").strip()
        if not summary_path:
            return ""
        resolved = DashboardOrchestrator._ensure_short_test_summary_path(
            project_name=project_name, summary_path=summary_path
        )
        return resolved or summary_path

    @staticmethod
    def _ensure_short_test_summary_path(*, project_name: str, summary_path: str) -> str:
        path = Path(summary_path).expanduser()
        if not path.is_file():
            return summary_path
        if path.name.startswith("ft_") and path.suffix == ".txt":
            return str(path)
        parents = path.parents
        if len(parents) < 4:
            return summary_path
        run_root = parents[3]
        digest = hashlib.sha1(project_name.encode("utf-8")).hexdigest()[:10]
        short_path = run_root / f"ft_{digest}.txt"
        if not short_path.exists():
            with suppress(OSError):
                short_path.write_text(path.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        return str(short_path) if short_path.exists() else summary_path

    def _print_project_action_failure_details(self, route: Route, state: RunState) -> bool:
        if route.command == "migrate":
            return self._print_migrate_result_details(route, state)
        metadata = state.metadata.get("project_action_reports")
        if not isinstance(metadata, dict):
            return False
        project_names = route.projects or self._project_name_list(
            self._project_names_from_state(state, cast(Any, self.runtime))
        )
        printed = False
        for project_name_raw in project_names:
            project_name = str(project_name_raw).strip()
            project_entry = metadata.get(project_name)
            if not isinstance(project_entry, dict):
                continue
            action_entry = project_entry.get(route.command)
            if not isinstance(action_entry, dict):
                continue
            if str(action_entry.get("status", "")).strip().lower() != "failed":
                continue
            summary = str(action_entry.get("summary", "")).strip()
            report_path = str(action_entry.get("report_path", "")).strip()
            if summary:
                summary_lines = [line.strip() for line in summary.splitlines() if line.strip()]
                first_line = summary_lines[0] if summary_lines else ""
                hint_lines = [line for line in summary_lines[1:] if line.lower().startswith("hint:")]
                if len(summary_lines) == 1 and len(first_line) <= 220:
                    print(f"{route.command} failed for {project_name}: {first_line}")
                else:
                    if first_line:
                        print(f"{route.command} failed for {project_name}: {first_line}")
                    for hint in hint_lines:
                        print(hint)
                    if report_path:
                        print(f"{route.command} failure log for {project_name}:")
                        print(
                            render_path_for_terminal(
                                report_path,
                                env=getattr(self.runtime, "env", {}),
                                stream=sys.stdout,
                                interactive_tty=True,
                            )
                        )
                printed = True
                continue
            if report_path:
                print(f"{route.command} failure log for {project_name}:")
                print(
                    render_path_for_terminal(
                        report_path,
                        env=getattr(self.runtime, "env", {}),
                        stream=sys.stdout,
                        interactive_tty=True,
                    )
                )
                printed = True
        return printed

    def _print_migrate_result_details(self, route: Route, state: RunState) -> bool:
        metadata = state.metadata.get("project_action_reports")
        if not isinstance(metadata, dict):
            return False
        project_names = route.projects or self._project_name_list(
            self._project_names_from_state(state, cast(Any, self.runtime))
        )
        records = []
        for project_name_raw in project_names:
            project_name = str(project_name_raw).strip()
            project_entry = metadata.get(project_name)
            action_entry = project_entry.get("migrate") if isinstance(project_entry, dict) else None
            record = ActionCommandOrchestrator._migrate_result_record(project_name=project_name, action_entry=action_entry)
            if record is None:
                continue
            records.append(record)
        if not records:
            return False
        ActionCommandOrchestrator._print_migrate_result_records(
            records=records,
            env=getattr(self.runtime, "env", {}),
            interactive_tty=True,
        )
        return True

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
        runtime_any = cast(Any, rt)
        default_branch = self._default_pr_base_branch(runtime_any)
        if self._route_has_explicit_target(route, runtime_any):
            route.flags = {**route.flags, "pr_base": route.flags.get("pr_base") or default_branch}
            return route

        projects = self._project_names_from_state(state, runtime_any)
        single_project = self._single_project_name(projects)
        if single_project:
            route.projects = [single_project]
            runtime_any._emit(
                "dashboard.target_scope.defaulted",
                command="pr",
                mode=state.mode,
                scope="single_project",
                project_count=1,
                projects=[single_project],
            )
        selection_raw = self._run_pr_selection_flow(
            projects=projects,
            initial_project_names=[single_project] if single_project else (),
            default_branch=default_branch,
            runtime=runtime_any,
        )
        if selection_raw is None:
            print(self._no_target_selected_message(route.command))
            return None
        selection = cast(Any, selection_raw)
        if selection.cancelled:
            if str(getattr(selection, "cancelled_step", "")).strip().lower() == "branch":
                print("No PR base branch selected.")
            else:
                print(self._no_target_selected_message(route.command))
            return None
        if selection.project_names:
            route.projects = list(selection.project_names)
        else:
            print(self._no_target_selected_message(route.command))
            return None
        if not isinstance(selection.base_branch, str) or not selection.base_branch.strip():
            print("No PR base branch selected.")
            return None
        base_branch = selection.base_branch.strip()
        route.flags = {**route.flags, "pr_base": base_branch}
        runtime_any._emit(
            "dashboard.pr_base.selected",
            command="pr",
            base_branch=base_branch,
            explicit=base_branch != default_branch,
        )
        raw = self._prompt_pr_message(runtime_any)
        if raw is None:
            print(self._no_target_selected_message(route.command))
            return None
        message = str(raw).strip()
        if message:
            route.flags = {**route.flags, "pr_body": message}
            runtime_any._emit(
                "dashboard.pr_body.selected",
                command="pr",
                explicit=True,
                length=len(message),
            )
        return route

    def _maybe_prepare_pr_commit(self, route: Route, state: RunState, rt: object) -> tuple[Route | None, RunState]:
        runtime_any = cast(Any, rt)
        dirty_reports = self._dirty_pr_reports(route, state, runtime_any)
        dirty_targets = [report for report in dirty_reports if report.dirty]
        runtime_any._emit(
            "dashboard.pr_dirty_state",
            command="pr",
            selected_project_count=len(dirty_reports),
            dirty_project_count=len(dirty_targets),
            staged=any(report.staged for report in dirty_targets),
            unstaged=any(report.unstaged for report in dirty_targets),
            untracked=any(report.untracked for report in dirty_targets),
        )
        if not dirty_targets:
            return route, state

        prompt = self._dirty_pr_prompt(dirty_targets)
        runtime_any._emit(
            "dashboard.pr_dirty_commit.prompt",
            command="pr",
            dirty_project_count=len(dirty_targets),
            staged=any(report.staged for report in dirty_targets),
            unstaged=any(report.unstaged for report in dirty_targets),
            untracked=any(report.untracked for report in dirty_targets),
        )
        decision = self._prompt_dirty_pr_menu(
            runtime_any,
            title="Commit dirty changes before PR?",
            prompt=prompt,
        )
        if decision == "cancel":
            runtime_any._emit("dashboard.pr_dirty_commit.cancelled", command="pr", dirty_project_count=len(dirty_targets))
            print("Cancelled PR creation.")
            return None, state
        if decision == "skip":
            runtime_any._emit("dashboard.pr_dirty_commit.declined", command="pr", dirty_project_count=len(dirty_targets))
            return route, state

        runtime_any._emit("dashboard.pr_dirty_commit.accepted", command="pr", dirty_project_count=len(dirty_targets))
        commit_route = Route(
            command="commit",
            mode=route.mode,
            raw_args=["commit"],
            passthrough_args=[],
            projects=[report.project_name for report in dirty_targets],
            flags={"batch": True, "interactive_command": True},
        )
        commit_route = self._apply_commit_selection(commit_route, state, runtime_any)
        if commit_route is None:
            runtime_any._emit("dashboard.pr_dirty_commit.cancelled", command="pr", dirty_project_count=len(dirty_targets))
            return None, state
        code = runtime_any.dispatch(commit_route)
        refreshed = runtime_any._try_load_existing_state(mode=state.mode, strict_mode_match=True)
        next_state = refreshed if refreshed is not None else state
        if code != 0:
            runtime_any._emit("dashboard.pr_dirty_commit.failed", command="pr", dirty_project_count=len(dirty_targets))
            self._print_interactive_failure_details(commit_route, next_state, code=code)
            return None, next_state
        runtime_any._emit("dashboard.pr_dirty_commit.completed", command="pr", dirty_project_count=len(dirty_targets))
        return route, next_state

    def _dirty_pr_reports(self, route: Route, state: RunState, runtime: Any) -> list[DirtyWorktreeReport]:
        repo_root = self._repo_root(runtime)
        project_roots = self._project_roots_for_route(route, state, runtime)
        reports_by_git_root: dict[str, DirtyWorktreeReport] = {}
        for project_name in route.projects or []:
            project_root = project_roots.get(project_name)
            if project_root is None:
                continue
            report = probe_dirty_worktree(project_root, repo_root, project_name=project_name)
            git_root_key = str(report.git_root.resolve())
            existing = reports_by_git_root.get(git_root_key)
            if existing is None:
                reports_by_git_root[git_root_key] = report
        return list(reports_by_git_root.values())

    def _dedupe_route_projects_by_git_root(self, route: Route, state: RunState, rt: object) -> Route:
        runtime_any = cast(Any, rt)
        if len(route.projects) <= 1:
            return route
        repo_root = self._repo_root(runtime_any)
        project_roots = self._project_roots_for_route(route, state, runtime_any)
        unique_projects: list[str] = []
        seen_git_roots: set[str] = set()
        collapsed = False
        for project_name in route.projects:
            project_root = project_roots.get(project_name)
            if project_root is None:
                unique_projects.append(project_name)
                continue
            git_root = resolve_git_root(project_root, repo_root)
            git_root_key = str(git_root.resolve())
            if git_root_key in seen_git_roots:
                collapsed = True
                continue
            seen_git_roots.add(git_root_key)
            unique_projects.append(project_name)
        if collapsed:
            route.projects = unique_projects
            runtime_any._emit(
                "dashboard.pr_target_scope.deduped_git_roots",
                command="pr",
                original_project_count=len(project_roots) if project_roots else len(route.projects),
                deduped_project_count=len(unique_projects),
                projects=list(unique_projects),
            )
        return route

    @staticmethod
    def _repo_root(runtime: Any) -> Path:
        base_dir = getattr(getattr(runtime, "config", None), "base_dir", Path.cwd())
        return Path(str(base_dir)).resolve()

    def _project_roots_for_route(self, route: Route, state: RunState, runtime: Any) -> dict[str, Path]:
        repo_root = self._repo_root(runtime)
        metadata = state.metadata if isinstance(state.metadata, dict) else {}
        raw_project_roots = metadata.get("project_roots")
        project_roots: dict[str, Path] = {}
        if isinstance(raw_project_roots, dict):
            for name, root in raw_project_roots.items():
                project_name = str(name).strip()
                root_raw = str(root or "").strip()
                if not project_name or not root_raw:
                    continue
                resolved = Path(root_raw)
                if not resolved.is_absolute():
                    resolved = repo_root / resolved
                project_roots[project_name] = resolved.resolve()
        for project_name in route.projects or []:
            if project_name in project_roots:
                continue
            if str(project_name).strip().casefold() == "main":
                project_roots[project_name] = repo_root
        return project_roots

    def _maybe_offer_review_tab_launch(self, route: Route, state: RunState, rt: object) -> None:
        runtime_any = cast(Any, rt)
        if not bool(route.flags.get(_REVIEW_TAB_LAUNCH_FLAG)):
            return
        target = self._review_tab_target(route, state, runtime_any)
        if target is None:
            runtime_any._emit("dashboard.review_tab.skipped", command="review", reason="ineligible_target_scope")
            return
        project_name, project_root = target
        launch_review_agent_terminal(
            runtime_any,
            repo_root=self._repo_root(runtime_any),
            project_name=project_name,
            project_root=project_root,
            review_bundle_path=self._review_bundle_path(state, project_name=project_name),
        )

    def _apply_review_tab_launch_selection(self, route: Route, state: RunState, rt: object) -> Route:
        runtime_any = cast(Any, rt)
        route.flags = {key: value for key, value in route.flags.items() if key != _REVIEW_TAB_LAUNCH_FLAG}
        target = self._review_tab_target(route, state, runtime_any)
        runtime_any._emit(
            "dashboard.review_tab.evaluate",
            command="review",
            project_count=len(route.projects or []),
            eligible=target is not None,
        )
        if target is None:
            runtime_any._emit("dashboard.review_tab.skipped", command="review", reason="ineligible_target_scope")
            return route
        project_name, _project_root = target
        readiness = review_agent_launch_readiness(runtime_any)
        if not readiness.ready:
            runtime_any._emit(
                "dashboard.review_tab.skipped",
                command="review",
                reason=readiness.reason,
                project=project_name,
                cli=readiness.cli,
                missing=list(readiness.missing),
            )
            message = self._review_tab_unavailable_message(readiness.reason, readiness.missing)
            if message:
                print(message)
            return route
        runtime_any._emit("dashboard.review_tab.prompt", command="review", project=project_name, cli=readiness.cli)
        decision = self._prompt_review_tab_menu(runtime_any, project_name=project_name)
        if decision != "commit":
            runtime_any._emit("dashboard.review_tab.declined", command="review", project=project_name, cli=readiness.cli)
            return route
        runtime_any._emit("dashboard.review_tab.accepted", command="review", project=project_name, cli=readiness.cli)
        route.flags = {**route.flags, _REVIEW_TAB_LAUNCH_FLAG: True}
        return route

    def _review_tab_target(self, route: Route, state: RunState, runtime: Any) -> tuple[str, Path] | None:
        repo_root = self._repo_root(runtime)
        project_roots = self._project_roots_for_route(route, state, runtime)
        distinct_targets: list[tuple[str, Path]] = []
        seen_git_roots: set[str] = set()
        for project_name in route.projects or []:
            project_root = project_roots.get(project_name)
            if project_root is None:
                continue
            git_root = resolve_git_root(project_root, repo_root)
            if git_root == repo_root and project_root != repo_root and not (project_root / ".git").exists():
                git_root = project_root
            git_root_key = str(git_root.resolve())
            if git_root_key in seen_git_roots:
                continue
            seen_git_roots.add(git_root_key)
            distinct_targets.append((project_name, project_root))
        if len(distinct_targets) != 1:
            return None
        project_name, project_root = distinct_targets[0]
        if str(project_name).strip().casefold() == "main":
            return None
        if project_root.resolve() == repo_root:
            return None
        return project_name, project_root

    @staticmethod
    def _review_tab_unavailable_message(reason: str, missing: tuple[str, ...]) -> str:
        if reason == "missing_executables" and missing:
            return f"Origin review tab unavailable: missing required executables: {', '.join(missing)}."
        if reason in {"missing_cmux_context", "workspace_unavailable"}:
            return "Origin review tab unavailable: current cmux workspace context is unavailable."
        return ""

    @staticmethod
    def _review_bundle_path(state: RunState, *, project_name: str) -> Path | None:
        metadata = state.metadata if isinstance(state.metadata, dict) else {}
        reports = metadata.get("project_action_reports")
        if not isinstance(reports, dict):
            return None
        project_entry = reports.get(project_name)
        if not isinstance(project_entry, dict):
            return None
        review_entry = project_entry.get("review")
        if not isinstance(review_entry, dict):
            return None
        if str(review_entry.get("status", "")).strip().lower() != "success":
            return None
        raw_path = str(review_entry.get("bundle_path", "") or "").strip()
        if not raw_path:
            return None
        return Path(raw_path).expanduser()

    @staticmethod
    def _dirty_pr_prompt(dirty_targets: list[DirtyWorktreeReport]) -> str:
        if len(dirty_targets) == 1:
            target = dirty_targets[0]
            return f"UNSTAGED CODE IN WORKTREE {target.project_name} - DO YOU WANT TO STAGE IT?"
        return "UNSTAGED CODE IN SELECTED WORKTREES - DO YOU WANT TO STAGE IT?"

    @staticmethod
    def _prompt_review_tab_menu(runtime: Any, *, project_name: str) -> DirtyPrDecision:
        prompt = f"Open an origin-side AI review tab for {project_name}?"
        values = _run_selector_with_impl(
            prompt=prompt,
            options=[
                SelectorItem(
                    id="review-tab:open",
                    label="Yes",
                    kind="",
                    token=_REVIEW_TAB_OPEN_TOKEN,
                    scope_signature=("review-tab:open",),
                ),
                SelectorItem(
                    id="review-tab:skip",
                    label="No",
                    kind="",
                    token=_REVIEW_TAB_SKIP_TOKEN,
                    scope_signature=("review-tab:skip",),
                ),
            ],
            multi=False,
            initial_tokens=[_REVIEW_TAB_SKIP_TOKEN],
            emit=getattr(runtime, "_emit", None),
        )
        if not values:
            return "skip"
        chosen = str(values[0]).strip()
        if chosen == _REVIEW_TAB_OPEN_TOKEN:
            return "commit"
        if chosen == _REVIEW_TAB_SKIP_TOKEN:
            return "skip"
        return DashboardOrchestrator._prompt_yes_no_dialog(runtime, title="Open origin review tab?", prompt=prompt)

    @staticmethod
    def _dirty_categories(report: DirtyWorktreeReport) -> list[str]:
        categories: list[str] = []
        if bool(getattr(report, "staged", False)):
            categories.append("staged changes")
        if bool(getattr(report, "unstaged", False)):
            categories.append("unstaged changes")
        if bool(getattr(report, "untracked", False)):
            categories.append("untracked files")
        return categories

    @staticmethod
    def _prompt_dirty_pr_menu(runtime: Any, *, title: str, prompt: str) -> DirtyPrDecision:
        values = _run_selector_with_impl(
            prompt=prompt,
            options=[
                SelectorItem(
                    id="dirty-pr:commit",
                    label="Commit",
                    kind="",
                    token="__DIRTY_PR_COMMIT__",
                    scope_signature=("dirty-pr:commit",),
                ),
                SelectorItem(
                    id="dirty-pr:skip",
                    label="Do nothing",
                    kind="",
                    token="__DIRTY_PR_SKIP__",
                    scope_signature=("dirty-pr:skip",),
                ),
            ],
            multi=False,
            initial_tokens=["__DIRTY_PR_COMMIT__"],
            emit=getattr(runtime, "_emit", None),
        )
        if not values:
            return "cancel"
        chosen = str(values[0]).strip()
        if chosen == "__DIRTY_PR_COMMIT__":
            return "commit"
        if chosen == "__DIRTY_PR_SKIP__":
            return "skip"
        return DashboardOrchestrator._prompt_yes_no_dialog(runtime, title=title, prompt=prompt)

    @staticmethod
    def _prompt_yes_no_dialog(runtime: Any, *, title: str, prompt: str) -> DirtyPrDecision:
        confirm = getattr(runtime, "_prompt_yes_no", None)
        if callable(confirm):
            try:
                result = confirm(title=title, prompt=prompt)
            except TypeError:
                result = confirm(prompt)
            if result is None:
                return "cancel"
            return "commit" if bool(result) else "skip"
        response = DashboardOrchestrator._read_interactive_line(runtime, prompt).strip().lower()
        if response in {"y", "yes"}:
            return "commit"
        if response in {"", "n", "no"}:
            return "skip"
        if response in {"c", "cancel", "q", "quit", "esc", "escape"}:
            return "cancel"
        return "skip"

    def _default_pr_base_branch(self, runtime: Any) -> str:
        git_root = self._pr_git_root(runtime)
        try:
            default_branch = detect_default_branch(git_root).strip()
        except Exception:
            default_branch = ""
        return default_branch or "main"

    def _pr_base_branch_options(self, runtime: Any, *, default_branch: str) -> list[SelectorItem]:
        git_root = self._pr_git_root(runtime)
        command = ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads"]
        listed = subprocess.run(
            command,
            cwd=str(git_root),
            text=True,
            capture_output=True,
            check=False,
        )
        branch_names = (
            [line.strip() for line in listed.stdout.splitlines() if line.strip()] if listed.returncode == 0 else []
        )
        if default_branch and default_branch not in branch_names:
            branch_names.append(default_branch)
        if not branch_names:
            branch_names = [default_branch or "main"]
        seen: set[str] = set()
        items: list[SelectorItem] = []
        for branch_name in sorted(branch_names, key=str.casefold):
            lowered = branch_name.casefold()
            if lowered in seen:
                continue
            seen.add(lowered)
            items.append(
                SelectorItem(
                    id=f"branch:{branch_name}",
                    label=branch_name,
                    kind="branch",
                    token=branch_name,
                    scope_signature=(f"branch:{branch_name}",),
                    section="Branches",
                )
            )
        return items

    def _pr_git_root(self, runtime: Any) -> Path:
        base_dir = getattr(getattr(runtime, "config", None), "base_dir", None)
        if isinstance(base_dir, Path):
            return resolve_git_root(base_dir, base_dir)
        if isinstance(base_dir, str) and base_dir.strip():
            candidate = Path(base_dir).resolve()
            return resolve_git_root(candidate, candidate)
        return Path.cwd()

    def _run_pr_selection_flow(
        self,
        *,
        projects: list[object],
        initial_project_names: tuple[str, ...] | list[str],
        default_branch: str,
        runtime: Any,
    ):
        return run_pr_flow(
            projects=projects,
            initial_project_names=initial_project_names,
            branch_options=self._pr_base_branch_options(runtime, default_branch=default_branch),
            default_branch=default_branch,
            emit=getattr(runtime, "_emit", None),
        )

    @staticmethod
    def _single_project_name(projects: list[object]) -> str:
        names = [
            str(getattr(project, "name", "")).strip()
            for project in projects
            if str(getattr(project, "name", "")).strip()
        ]
        if len(names) != 1:
            return ""
        return names[0]

    @staticmethod
    def _interactive_target_prompt(command: str) -> str:
        label_map = {
            "stop": "Stop services",
            "test": "Run tests for",
            "logs": "Tail logs for",
            "clear-logs": "Clear logs for",
            "errors": "Errors for",
            "pr": "Create PR for",
            "commit": "Commit changes for",
            "review": "Review changes for",
            "migrate": "Run migrations for",
            "blast-worktree": "Blast and delete worktree for",
        }
        return label_map.get(command, f"Select {command} target")

    @staticmethod
    def _no_target_selected_message(command: str) -> str:
        return no_target_selected_message(command, route=None, interactive_allowed=True)

    def _apply_restart_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        runtime_any = cast(Any, rt)
        if self._route_has_explicit_target(route, runtime_any):
            if bool(route.flags.get("all")):
                route.flags = {**route.flags, "restart_include_requirements": True}
            else:
                route.flags = {**route.flags, "restart_include_requirements": False}
            return route
        projects = self._project_names_from_state(state, runtime_any)
        selected_projects = self._select_dashboard_projects(
            command="restart",
            state=state,
            projects=projects,
            runtime=runtime_any,
        )
        if selected_projects is None:
            print("No restart target selected.")
            return None
        route.projects = list(selected_projects)

        selected_service_types = self._select_dashboard_service_types(
            command="restart",
            state=state,
            selected_projects=selected_projects,
            runtime=runtime_any,
        )
        if selected_service_types is None:
            print("No restart target selected.")
            return None
        selected_service_names = self._service_names_for_projects_and_types(
            state,
            runtime_any,
            project_names=selected_projects,
            service_types=selected_service_types,
        )
        all_project_names = self._project_name_list(projects)
        all_service_types = self._available_service_types_for_projects(
            state,
            runtime_any,
            project_names=all_project_names,
        )
        include_requirements = set(selected_projects) == set(all_project_names) and set(selected_service_types) == set(
            all_service_types
        )
        route.flags = {
            **{
                key: value
                for key, value in route.flags.items()
                if key not in {"all", "services", "restart_service_types"}
            },
            "services": selected_service_names,
            "restart_service_types": list(selected_service_types),
            "restart_include_requirements": include_requirements,
        }
        return route

    def _default_interactive_targets(self, route: Route, state: RunState, rt: object) -> Route:
        _ = state, rt
        return route

    @staticmethod
    def _route_has_explicit_target(route: Route, runtime: object) -> bool:
        return route_has_explicit_target(route, cast(Any, runtime))

    @staticmethod
    def _restart_service_types_from_service_names(service_names: list[str]) -> list[str]:
        types: list[str] = []
        seen: set[str] = set()
        for name in service_names:
            normalized = str(name).strip().lower()
            service_type = ""
            if normalized.endswith(" backend"):
                service_type = "backend"
            elif normalized.endswith(" frontend"):
                service_type = "frontend"
            if service_type and service_type not in seen:
                seen.add(service_type)
                types.append(service_type)
        return types

    @staticmethod
    def _service_types_from_service_names(service_names: list[str]) -> set[str]:
        return service_types_from_service_names(service_names)

    @staticmethod
    def _project_names_from_state(state: RunState, rt: object) -> list[object]:
        return project_names_from_state(cast(Any, rt), state)

    @staticmethod
    def _project_name_list(projects: list[object]) -> list[str]:
        return [name for name in (str(getattr(project, "name", "")).strip() for project in projects) if name]

    def _select_dashboard_projects(
        self,
        *,
        command: str,
        state: RunState,
        projects: list[object],
        runtime: Any,
    ) -> list[str] | None:
        project_names = self._project_name_list(projects)
        single_project = self._single_project_name(projects)
        if single_project:
            runtime._emit(
                "dashboard.target_scope.defaulted",
                command=command,
                mode=state.mode,
                scope="single_project",
                project_count=1,
                projects=[single_project],
            )
            return [single_project]
        initial_project_names = self._dashboard_preselected_projects(
            state=state,
            projects=projects,
            runtime=runtime,
        )
        selection = runtime._select_project_targets(
            prompt=self._worktree_prompt(command),
            projects=projects,
            allow_all=False,
            allow_untested=False,
            multi=True,
            initial_project_names=initial_project_names,
        )
        if selection.cancelled:
            return None
        selected = [name for name in selection.project_names if name]
        return selected or project_names

    @staticmethod
    def _dashboard_preselected_projects(
        *,
        state: RunState,
        projects: list[object],
        runtime: Any,
    ) -> list[str]:
        if str(state.mode).strip().lower() != "trees":
            return []
        startup = getattr(runtime, "startup_orchestrator", None)
        if startup is None:
            return []
        try:
            return list(
                _tree_preselected_projects_from_state_impl(
                    startup,
                    runtime=runtime,
                    project_contexts=cast(Any, projects),
                )
            )
        except Exception:
            return []

    def _select_dashboard_service_types(
        self,
        *,
        command: str,
        state: RunState,
        selected_projects: list[str],
        runtime: Any,
    ) -> list[str] | None:
        if command == "test":
            return self._select_dashboard_test_scope(
                state=state,
                selected_projects=selected_projects,
                runtime=runtime,
            )
        available_types = self._available_service_types_for_projects(
            state,
            runtime,
            project_names=selected_projects,
        )
        all_tests_available = command == "test" and self._all_tests_scope_available(
            state,
            runtime,
            project_names=selected_projects,
        )
        failed_scope_available = command == "test" and self._failed_test_scope_available(
            state,
            project_names=selected_projects,
        )
        if (
            len(available_types) <= 1
            and not failed_scope_available
            and not (all_tests_available and not available_types)
        ):
            return list(available_types)
        default_service_names = [service_type.title() for service_type in available_types]
        initial_service_names = list(default_service_names)
        if all_tests_available and not available_types:
            default_service_names.append("All tests")
            initial_service_names.append("All tests")
        if failed_scope_available:
            default_service_names.append("All failed tests")
            if not initial_service_names:
                initial_service_names.append("All failed tests")
        selection = runtime._select_project_targets(
            prompt=self._service_prompt(command),
            projects=[SimpleProject(name=label) for label in default_service_names],
            allow_all=False,
            allow_untested=False,
            multi=True,
            initial_project_names=initial_service_names,
        )
        if selection.cancelled:
            return None
        selected_types: list[str] = []
        for name in selection.project_names:
            normalized = name.strip().lower()
            if not normalized:
                continue
            if normalized == "all tests":
                selected_types.append("all")
                continue
            if normalized == "all failed tests":
                selected_types.append("failed")
                continue
            selected_types.append(normalized)
        return selected_types or list(available_types)

    def _select_dashboard_test_scope(
        self,
        *,
        state: RunState,
        selected_projects: list[str],
        runtime: Any,
    ) -> list[str] | None:
        available_types = self._available_service_types_for_projects(
            state,
            runtime,
            project_names=selected_projects,
        )
        all_tests_available = self._all_tests_scope_available(
            state,
            runtime,
            project_names=selected_projects,
        )
        failed_scope_available = self._failed_test_scope_available(
            state,
            project_names=selected_projects,
        )
        if (
            len(available_types) <= 1
            and not failed_scope_available
            and not (all_tests_available and not available_types)
        ):
            return list(available_types)
        options: list[str] = []
        initial_names: list[str] = []
        for service_type in available_types:
            label = service_type.title()
            options.append(label)
            initial_names.append(label)
        if all_tests_available and not available_types:
            options.append("All tests")
            initial_names.append("All tests")
        if failed_scope_available:
            options.append("Failed tests")
        if not options:
            return []
        if len(options) == 1:
            only = options[0].strip().lower()
            if only == "all tests":
                return ["all"]
            if only == "failed tests":
                return ["failed"]
            return [only]
        selection = runtime._select_project_targets(
            prompt=self._service_prompt("test"),
            projects=[SimpleProject(name=label) for label in options],
            allow_all=False,
            allow_untested=False,
            multi=True,
            initial_project_names=initial_names,
            exclusive_project_name="Failed tests" if failed_scope_available else None,
        )
        if selection.cancelled:
            return None
        chosen_types = [str(name).strip().lower() for name in selection.project_names if str(name).strip()]
        if not chosen_types:
            return None
        if "failed tests" in chosen_types:
            return ["failed"]
        if "all tests" in chosen_types:
            return ["all"]
        return [name for name in chosen_types if name in {"backend", "frontend"}]

    @staticmethod
    def _all_tests_scope_available(
        state: RunState,
        runtime: Any,
        *,
        project_names: list[str],
    ) -> bool:
        if not project_names:
            return False
        metadata = state.metadata if isinstance(state.metadata, dict) else {}
        project_roots_raw = metadata.get("project_roots")
        project_roots = project_roots_raw if isinstance(project_roots_raw, dict) else {}
        repo_root = Path(str(getattr(getattr(runtime, "config", None), "base_dir", Path.cwd())))
        for project_name in project_names:
            root_raw = str(project_roots.get(project_name, "") or "").strip()
            project_root = repo_root if not root_raw else Path(root_raw)
            if not project_root.is_absolute():
                project_root = repo_root / project_root
            try:
                if default_test_commands(project_root):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _failed_test_scope_available(state: RunState, *, project_names: list[str]) -> bool:
        metadata = state.metadata.get("project_test_summaries")
        if not isinstance(metadata, dict):
            return False
        requested = {name.casefold() for name in project_names}
        for project_name, entry in metadata.items():
            if requested and str(project_name).casefold() not in requested:
                continue
            if not isinstance(entry, dict):
                continue
            status = str(entry.get("status", "") or "").strip().lower()
            if status == "passed":
                continue
            for key in ("failed_tests", "failed_manifest_entries"):
                raw_count = entry.get(key)
                with suppress(TypeError, ValueError):
                    if int(raw_count) > 0:
                        return True
            if summary_excerpt_from_entry(entry, max_lines=1):
                return True
            if str(entry.get("manifest_path", "") or "").strip():
                return True
            if str(entry.get("short_summary_path", "") or "").strip():
                return True
            if str(entry.get("summary_path", "") or "").strip():
                return True
            if status == "failed":
                return True
        return False

    @staticmethod
    def _available_service_types_for_projects(
        state: RunState,
        runtime: Any,
        *,
        project_names: list[str],
    ) -> list[str]:
        requested = {name.casefold() for name in project_names}
        ordered: list[str] = []
        seen: set[str] = set()
        for service_name in state.services:
            project_name = str(runtime._project_name_from_service(service_name) or "").strip()
            if not project_name:
                project_name = str(project_name_from_service_name(str(service_name))).strip()
            if requested and project_name.casefold() not in requested:
                continue
            normalized = str(service_name).strip().lower()
            service_type = ""
            if normalized.endswith(" backend") or normalized == "backend":
                service_type = "backend"
            elif normalized.endswith(" frontend") or normalized == "frontend":
                service_type = "frontend"
            if service_type and service_type not in seen:
                seen.add(service_type)
                ordered.append(service_type)
        if ordered:
            return ordered
        configured_service_types_raw = state.metadata.get("dashboard_configured_service_types")
        if isinstance(configured_service_types_raw, list):
            for service_type in configured_service_types_raw:
                normalized = str(service_type).strip().lower()
                if normalized not in {"backend", "frontend"}:
                    continue
                if normalized in seen:
                    continue
                seen.add(normalized)
                ordered.append(normalized)
        return ordered

    @staticmethod
    def _service_names_for_projects_and_types(
        state: RunState,
        runtime: Any,
        *,
        project_names: list[str],
        service_types: list[str],
    ) -> list[str]:
        requested_projects = {name.casefold() for name in project_names}
        requested_types = {name.casefold() for name in service_types}
        selected: list[str] = []
        for service_name in state.services:
            project_name = str(runtime._project_name_from_service(service_name) or "").strip()
            if not project_name:
                project_name = str(project_name_from_service_name(str(service_name))).strip()
            if requested_projects and project_name.casefold() not in requested_projects:
                continue
            normalized = str(service_name).strip().lower()
            service_type = ""
            if normalized.endswith(" backend") or normalized == "backend":
                service_type = "backend"
            elif normalized.endswith(" frontend") or normalized == "frontend":
                service_type = "frontend"
            if service_type and service_type.casefold() in requested_types:
                selected.append(service_name)
        return selected

    @staticmethod
    def _worktree_prompt(command: str) -> str:
        prompt_map = {
            "test": "Choose worktrees to test",
            "restart": "Choose worktrees",
        }
        return prompt_map.get(command, "Choose worktrees")

    @staticmethod
    def _service_prompt(command: str) -> str:
        prompt_map = {
            "test": "Choose test scope",
            "restart": "Choose services",
        }
        return prompt_map.get(command, "Choose services")

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
    def _dispatch_session_command(runtime_any: Any) -> None:
        try:
            from envctl_engine.runtime.session_management import print_session_list  # noqa: PLC0415
            from pathlib import Path  # noqa: PLC0415
            runtime_root = getattr(runtime_any.config, "base_dir", Path.cwd())
            print_session_list(Path(runtime_root))
        except Exception as exc:
            print(f"Error listing sessions: {exc}")

    @staticmethod
    def _dispatch_session_attach(runtime_any: Any) -> None:
        try:
            from envctl_engine.runtime.session_management import list_tmux_sessions  # noqa: PLC0415
            sessions = list_tmux_sessions()
            if not sessions:
                print("No active tmux sessions.")
                return
            print(f"Found {len(sessions)} active tmux session(s):")
            for i, s in enumerate(sessions):
                print(f"  {i+1}. {s['name']} (windows: {s['windows']})")
                print(f"     attach: {s['attach']}")
                print(f"     kill:   {s['kill']}")
            if len(sessions) == 1:
                print(f"\nTo attach, run: {sessions[0]['attach']}")
        except Exception as exc:
            print(f"Error listing sessions: {exc}")

    @staticmethod
    def _recover_single_letter_command_from_escape_fragment(raw: str) -> str:
        return recover_single_letter_command_from_escape_fragment(raw)

    @staticmethod
    def _parse_interactive_command(raw: str) -> list[str] | None:
        return parse_interactive_command(raw)

    @staticmethod
    def _tokens_set_mode(tokens: list[str]) -> bool:
        return tokens_set_mode(tokens)
