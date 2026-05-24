from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.dashboard.orchestrator import DashboardOrchestrator
from envctl_engine.ui.target_selector import TargetSelection

from tests.python.ui.dashboard_orchestrator_test_support import (
    _DashboardOrchestratorTestCase,
    _RuntimeStub,
)


class DashboardOrchestratorReviewTabTests(_DashboardOrchestratorTestCase):
    def test_successful_single_worktree_review_selects_origin_tab_before_dispatch_and_launches_after_success(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        order: list[str] = []
        state = RunState(
            run_id="run-review",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
            metadata={
                "project_roots": {"feature-a-1": "trees/feature-a/1"},
                "project_action_reports": {
                    "feature-a-1": {
                        "review": {
                            "status": "success",
                            "bundle_path": "/tmp/review-output/all.md",
                        }
                    }
                },
            },
        )
        runtime._latest_state = state

        def dispatch(route: Route) -> int:
            order.append("dispatch")
            runtime.last_dispatched_route = route
            runtime.dispatched_routes.append(route)
            return 0

        runtime.dispatch = dispatch  # type: ignore[assignment]

        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(ready=True, reason="ready", cli="codex"),
            ),
            patch(
                "envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl",
                side_effect=lambda **_kwargs: (order.append("selector") or ["__REVIEW_TAB_OPEN__"]),
            ) as selector_mock,
            patch(
                "envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal",
                side_effect=lambda *args, **kwargs: (
                    order.append("launch") or SimpleNamespace(status="launched", reason="launched")
                ),
            ) as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(order, ["selector", "dispatch", "launch"])
        self.assertEqual(runtime.confirm_prompts, [])
        selector_kwargs = selector_mock.call_args.kwargs
        self.assertEqual(selector_kwargs["prompt"], "Open an origin-side AI review tab for feature-a-1?")
        self.assertEqual([item.label for item in selector_kwargs["options"]], ["Yes", "No"])
        self.assertEqual(selector_kwargs["multi"], False)
        launch_mock.assert_called_once_with(
            runtime,
            repo_root=runtime.config.base_dir,
            project_name="feature-a-1",
            project_root=(runtime.config.base_dir / "trees" / "feature-a" / "1").resolve(),
            review_bundle_path=Path("/tmp/review-output/all.md"),
        )

    def test_successful_single_worktree_review_decline_keeps_existing_behavior(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-decline",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
            metadata={"project_roots": {"feature-a-1": "trees/feature-a/1"}},
        )
        runtime._latest_state = state

        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(ready=True, reason="ready", cli="codex"),
            ),
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__REVIEW_TAB_SKIP__"]),
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        launch_mock.assert_not_called()

    def test_failed_review_does_not_launch_origin_tab_after_preselected_opt_in(self) -> None:
        runtime = _RuntimeStub()
        runtime.dispatch_code = 1
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-fail",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
            metadata={"project_roots": {"feature-a-1": "trees/feature-a/1"}},
        )
        runtime._latest_state = state

        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(ready=True, reason="ready", cli="codex"),
            ) as readiness_mock,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__REVIEW_TAB_OPEN__"]) as selector_mock,
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        readiness_mock.assert_called_once()
        selector_mock.assert_called_once()
        launch_mock.assert_not_called()

    def test_main_review_does_not_prompt_for_origin_tab(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-main",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
            metadata={"project_roots": {"Main": "."}},
        )
        runtime._latest_state = state

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness") as readiness_mock,
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        readiness_mock.assert_not_called()
        launch_mock.assert_not_called()

    def test_multi_target_review_does_not_prompt_for_origin_tab(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["feature-a-1", "feature-b-1"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-multi",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "feature-b-1 Backend": ServiceRecord(
                    name="feature-b-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=101,
                    requested_port=8001,
                    actual_port=8001,
                    status="running",
                ),
            },
            metadata={
                "project_roots": {
                    "feature-a-1": "trees/feature-a/1",
                    "feature-b-1": "trees/feature-b/1",
                }
            },
        )
        runtime._latest_state = state

        with (
            patch("envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness") as readiness_mock,
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        readiness_mock.assert_not_called()
        launch_mock.assert_not_called()

    def test_review_tab_selector_cancel_behaves_like_decline_and_still_runs_review(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-cancel-menu",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
            metadata={"project_roots": {"feature-a-1": "trees/feature-a/1"}},
        )
        runtime._latest_state = state

        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(ready=True, reason="ready", cli="codex"),
            ),
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=None) as selector_mock,
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        selector_mock.assert_called_once()
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["review"])
        launch_mock.assert_not_called()

    def test_typed_review_with_explicit_project_still_uses_selector_when_eligible(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-explicit",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
            metadata={"project_roots": {"feature-a-1": "trees/feature-a/1"}},
        )
        runtime._latest_state = state

        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(ready=True, reason="ready", cli="codex"),
            ),
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__REVIEW_TAB_SKIP__"]) as selector_mock,
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command(
                "review --project feature-a-1",
                state,
                runtime,
            )

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        selector_mock.assert_called_once()
        launch_mock.assert_not_called()

    def test_review_tab_unavailable_skips_selector_and_prints_message_before_dispatch(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-no-cmux",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                )
            },
            metadata={"project_roots": {"feature-a-1": "trees/feature-a/1"}},
        )
        runtime._latest_state = state

        out = StringIO()
        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(
                    ready=False,
                    reason="missing_cmux_context",
                    cli="codex",
                    missing=(),
                ),
            ) as readiness_mock,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl") as selector_mock,
            patch("envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal") as launch_mock,
            redirect_stdout(out),
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        readiness_mock.assert_called_once()
        selector_mock.assert_not_called()
        self.assertEqual([route.command for route in runtime.dispatched_routes], ["review"])
        launch_mock.assert_not_called()
        self.assertIn("Origin review tab unavailable: current cmux workspace context is unavailable.", out.getvalue())

    def test_duplicate_review_targets_collapsing_to_one_git_root_prompt_once(self) -> None:
        runtime = _RuntimeStub()
        runtime.next_selection = TargetSelection(project_names=["feature-a-1", "feature-b-1"])
        orchestrator = DashboardOrchestrator(runtime)
        state = RunState(
            run_id="run-review-duplicate-root",
            mode="trees",
            services={
                "feature-a-1 Backend": ServiceRecord(
                    name="feature-a-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=100,
                    requested_port=8000,
                    actual_port=8000,
                    status="running",
                ),
                "feature-b-1 Backend": ServiceRecord(
                    name="feature-b-1 Backend",
                    type="backend",
                    cwd=".",
                    pid=101,
                    requested_port=8001,
                    actual_port=8001,
                    status="running",
                ),
            },
            metadata={
                "project_roots": {
                    "feature-a-1": "trees/shared/1",
                    "feature-b-1": "trees/shared/1",
                },
                "project_action_reports": {
                    "feature-a-1": {
                        "review": {
                            "status": "success",
                            "bundle_path": "/tmp/review-output/all.md",
                        }
                    }
                },
            },
        )
        runtime._latest_state = state

        with (
            patch(
                "envctl_engine.ui.dashboard.orchestrator.review_agent_launch_readiness",
                return_value=SimpleNamespace(ready=True, reason="ready", cli="codex"),
            ) as readiness_mock,
            patch("envctl_engine.ui.dashboard.orchestrator._run_selector_with_impl", return_value=["__REVIEW_TAB_OPEN__"]) as selector_mock,
            patch(
                "envctl_engine.ui.dashboard.orchestrator.launch_review_agent_terminal",
                return_value=SimpleNamespace(status="launched", reason="launched"),
            ) as launch_mock,
        ):
            should_continue, next_state = orchestrator._run_interactive_command("a", state, runtime)

        self.assertTrue(should_continue)
        self.assertIs(next_state, state)
        self.assertEqual(runtime.confirm_prompts, [])
        readiness_mock.assert_called_once()
        selector_mock.assert_called_once()
        launch_mock.assert_called_once()
