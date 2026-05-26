from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from envctl_engine.actions.project_action_domain import DirtyWorktreeReport
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard import pr_and_target_support
from envctl_engine.ui.selector_model import SelectorItem


DirtyPrDecision = Literal["commit", "skip", "cancel"]


class DashboardPrFlowMixin:
    def _apply_pr_selection(self, route: Route, state: RunState, rt: object) -> Route | None:
        return pr_and_target_support.apply_pr_selection(self, route, state, rt)

    def _maybe_prepare_pr_commit(self, route: Route, state: RunState, rt: object) -> tuple[Route | None, RunState]:
        return pr_and_target_support.maybe_prepare_pr_commit(self, route, state, rt)

    @staticmethod
    def _pr_dependencies() -> pr_and_target_support.DashboardPrDependencies:
        from envctl_engine.ui.dashboard import orchestrator

        return pr_and_target_support.DashboardPrDependencies(
            probe_dirty_worktree=orchestrator.probe_dirty_worktree,
            launch_review_agent_terminal=orchestrator.launch_review_agent_terminal,
            review_agent_launch_readiness=orchestrator.review_agent_launch_readiness,
            run_selector=orchestrator._run_selector_with_impl,
        )

    def _dirty_pr_reports(self, route: Route, state: RunState, runtime: Any) -> list[DirtyWorktreeReport]:
        return pr_and_target_support.dirty_pr_reports(
            self,
            route,
            state,
            runtime,
            dependencies=self._pr_dependencies(),
        )

    def _dedupe_route_projects_by_git_root(self, route: Route, state: RunState, rt: object) -> Route:
        return pr_and_target_support.dedupe_route_projects_by_git_root(self, route, state, rt)

    @staticmethod
    def _repo_root(runtime: Any) -> Path:
        return pr_and_target_support.repo_root_from_runtime(runtime)

    def _project_roots_for_route(self, route: Route, state: RunState, runtime: Any) -> dict[str, Path]:
        return pr_and_target_support.project_roots_for_route(self, route, state, runtime)

    def _maybe_offer_review_tab_launch(self, route: Route, state: RunState, rt: object) -> None:
        pr_and_target_support.maybe_offer_review_tab_launch(
            self,
            route,
            state,
            rt,
            dependencies=self._pr_dependencies(),
        )

    def _apply_review_tab_launch_selection(self, route: Route, state: RunState, rt: object) -> Route:
        return pr_and_target_support.apply_review_tab_launch_selection(
            self,
            route,
            state,
            rt,
            dependencies=self._pr_dependencies(),
        )

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

    def _prompt_review_tab_menu(self, runtime: Any, *, project_name: str) -> DirtyPrDecision:
        return pr_and_target_support.prompt_review_tab_menu(
            runtime,
            project_name=project_name,
            dependencies=self._pr_dependencies(),
        )

    @staticmethod
    def _dirty_categories(report: DirtyWorktreeReport) -> list[str]:
        return pr_and_target_support.dirty_categories(report)

    def _prompt_dirty_pr_menu(self, runtime: Any, *, title: str, prompt: str) -> DirtyPrDecision:
        return pr_and_target_support.prompt_dirty_pr_menu(
            runtime,
            title=title,
            prompt=prompt,
            dependencies=self._pr_dependencies(),
        )

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
