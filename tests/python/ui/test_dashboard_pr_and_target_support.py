from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path
import unittest
from unittest import mock

from envctl_engine.actions.project_action_domain import DirtyWorktreeReport
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard import pr_and_target_support
from envctl_engine.ui.dashboard.pr_flow import PrFlowResult


def _route(command: str = "pr", **kwargs: object) -> Route:
    defaults: dict[str, object] = {
        "mode": "dev",
        "raw_args": [command],
        "passthrough_args": [],
        "projects": [],
        "flags": {},
    }
    defaults.update(kwargs)
    return Route(command=command, **defaults)  # type: ignore[arg-type]


def _state(**kwargs: object) -> RunState:
    defaults: dict[str, object] = {"run_id": "r1", "mode": "dev", "services": {}, "metadata": {}}
    defaults.update(kwargs)
    return RunState(**defaults)  # type: ignore[arg-type]


class _Owner:
    def __init__(self) -> None:
        self.events: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.pr_flow_result: PrFlowResult | None = PrFlowResult(["Main"], "release")
        self.pr_flow_calls: list[dict[str, object]] = []
        self.prompt_pr_message: str | None = "Ship body"
        self.dirty_reports: list[DirtyWorktreeReport] = []
        self.commit_selection: Route | None = None
        self.failure_details_calls: list[tuple[Route, RunState, int]] = []

    @staticmethod
    def _default_pr_base_branch(_runtime: object) -> str:
        return "main"

    @staticmethod
    def _route_has_explicit_target(route: Route, _runtime: object) -> bool:
        return bool(route.projects or route.flags.get("all") or route.flags.get("services"))

    @staticmethod
    def _project_names_from_state(_state: RunState, _runtime: object) -> list[object]:
        return [SimpleNamespace(name="Main")]

    @staticmethod
    def _single_project_name(projects: list[object]) -> str:
        return pr_and_target_support.single_project_name(projects)

    def _run_pr_selection_flow(self, **kwargs: object) -> PrFlowResult | None:
        self.pr_flow_calls.append(kwargs)
        return self.pr_flow_result

    @staticmethod
    def _no_target_selected_message(command: str) -> str:
        return f"No {command} target selected."

    def _prompt_pr_message(self, _runtime: object) -> str | None:
        return self.prompt_pr_message

    def _dirty_pr_reports(self, _route: Route, _state: RunState, _runtime: object) -> list[DirtyWorktreeReport]:
        return self.dirty_reports

    @staticmethod
    def _prompt_dirty_pr_menu(_runtime: object, *, title: str, prompt: str) -> str:  # noqa: ARG004
        return "commit"

    def _apply_commit_selection(self, route: Route, _state: RunState, _runtime: object) -> Route | None:
        self.commit_selection = route
        return route

    def _print_interactive_failure_details(self, route: Route, state: RunState, *, code: int) -> None:
        self.failure_details_calls.append((route, state, code))


class _Runtime:
    def __init__(self) -> None:
        self.events: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.dispatched: list[Route] = []
        self.dispatch_code = 0
        self.loaded_state: RunState | None = None

    def _emit(self, *args: object, **kwargs: object) -> None:
        self.events.append((args, kwargs))

    def dispatch(self, route: Route) -> int:
        self.dispatched.append(route)
        return self.dispatch_code

    def _try_load_existing_state(self, *, mode: str, strict_mode_match: bool) -> RunState | None:  # noqa: ARG002
        return self.loaded_state


def _dirty(project_name: str = "Main") -> DirtyWorktreeReport:
    return DirtyWorktreeReport(
        project_name=project_name,
        project_root=Path("/tmp") / project_name,
        git_root=Path("/tmp") / project_name,
        staged=True,
        unstaged=True,
        untracked=False,
    )


class DashboardPrAndTargetSupportTests(unittest.TestCase):
    def test_dirty_pr_reports_uses_explicit_dependencies(self) -> None:
        calls: list[tuple[Path, Path, str]] = []

        def probe(project_root: Path, repo_root: Path, *, project_name: str) -> DirtyWorktreeReport:
            calls.append((project_root, repo_root, project_name))
            return DirtyWorktreeReport(
                project_name=project_name,
                project_root=project_root,
                git_root=project_root,
                staged=True,
                unstaged=False,
                untracked=False,
            )

        dependencies = pr_and_target_support.DashboardPrDependencies(
            probe_dirty_worktree=probe,
            launch_review_agent_terminal=lambda *args, **kwargs: None,
            review_agent_launch_readiness=lambda *args, **kwargs: None,
            run_selector=lambda *args, **kwargs: None,
        )
        runtime = SimpleNamespace(config=SimpleNamespace(base_dir=Path("/repo")))
        state = _state(metadata={"project_roots": {"Main": "apps/main"}})

        reports = pr_and_target_support.dirty_pr_reports(
            _Owner(),
            _route(projects=["Main"]),
            state,
            runtime,
            dependencies=dependencies,
        )

        self.assertEqual([report.project_name for report in reports], ["Main"])
        self.assertEqual(calls, [(Path("/repo/apps/main"), Path("/repo"), "Main")])

    def test_apply_pr_selection_records_base_and_body_after_target_flow(self) -> None:
        owner = _Owner()
        runtime = _Runtime()
        route = _route()

        result = pr_and_target_support.apply_pr_selection(owner, route, _state(), runtime)

        self.assertIs(result, route)
        self.assertEqual(route.projects, ["Main"])
        self.assertEqual(route.flags["pr_base"], "release")
        self.assertEqual(route.flags["pr_body"], "Ship body")
        self.assertEqual(owner.pr_flow_calls[0]["default_branch"], "main")
        self.assertIn((('dashboard.pr_base.selected',), {'command': 'pr', 'base_branch': 'release', 'explicit': True}), runtime.events)

    def test_apply_pr_selection_cancels_when_branch_step_cancelled(self) -> None:
        owner = _Owner()
        owner.pr_flow_result = PrFlowResult([], None, cancelled=True, cancelled_step="branch")
        runtime = _Runtime()

        with mock.patch("builtins.print") as printed:
            result = pr_and_target_support.apply_pr_selection(owner, _route(), _state(), runtime)

        self.assertIsNone(result)
        printed.assert_called_with("No PR base branch selected.")

    def test_maybe_prepare_pr_commit_commits_only_dirty_targets(self) -> None:
        owner = _Owner()
        runtime = _Runtime()
        owner.dirty_reports = [_dirty("Main")]
        route = _route(projects=["Main"])

        result, next_state = pr_and_target_support.maybe_prepare_pr_commit(owner, route, _state(), runtime)

        self.assertIs(result, route)
        self.assertEqual(next_state.run_id, "r1")
        self.assertEqual([dispatched.command for dispatched in runtime.dispatched], ["commit"])
        self.assertEqual(runtime.dispatched[0].projects, ["Main"])
        self.assertEqual(runtime.dispatched[0].flags["batch"], True)

    def test_maybe_prepare_pr_commit_reports_failed_commit_details(self) -> None:
        owner = _Owner()
        runtime = _Runtime()
        runtime.dispatch_code = 7
        owner.dirty_reports = [_dirty("Main")]
        route = _route(projects=["Main"])
        state = _state()

        result, next_state = pr_and_target_support.maybe_prepare_pr_commit(owner, route, state, runtime)

        self.assertIsNone(result)
        self.assertIs(next_state, state)
        self.assertEqual(len(owner.failure_details_calls), 1)
        self.assertEqual(owner.failure_details_calls[0][2], 7)


if __name__ == "__main__":
    unittest.main()
