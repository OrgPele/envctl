# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.startup.startup_orchestrator_flow_test_support import *


class StartupOrchestratorFlowFailureTests(StartupOrchestratorFlowTestCase):
    def test_strict_truth_failure_terminates_started_services_and_writes_failed_state_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"ENVCTL_RUNTIME_TRUTH_MODE": "strict"})

            route = parse_route(["start", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"})
            result = ProjectStartupResult(
                requirements=RequirementsResult(project="Main", health="healthy"),
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=1234,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                warnings=[],
            )
            terminated: list[dict[str, ServiceRecord]] = []

            with (
                patch.object(engine, "_start_project_context", return_value=result),
                patch.object(engine, "_reconcile_state_truth", return_value=["Main Backend"]),
                patch.object(engine, "_write_artifacts") as write_artifacts_mock,
                patch.object(
                    engine, "_terminate_started_services", side_effect=lambda services: terminated.append(services)
                ),
            ):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(len(terminated), 1)
            self.assertEqual(write_artifacts_mock.call_count, 1)
            written_state = write_artifacts_mock.call_args.args[0]
            self.assertTrue(written_state.metadata["failed"])
            self.assertIn("failure_message", written_state.metadata)
            self.assertIn("Main Backend", written_state.services)

    def test_omx_ultragoal_headless_plan_agent_handoff_survives_local_startup_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )
            attach_target = PlanAgentAttachTarget(
                repo_root=repo,
                session_name="omx-feature-session",
                window_name="",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-feature-session"),
            )
            launch_result = PlanAgentLaunchResult(
                status="launched",
                reason="launched",
                outcomes=(
                    PlanAgentLaunchOutcome(
                        worktree_name=context.name,
                        worktree_root=Path(context.root),
                        surface_id=None,
                        status="launched",
                    ),
                ),
                attach_target=attach_target,
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals", return_value=launch_result),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_display_message_succeeds", return_value=(True, "%42")),
                patch.object(
                    engine,
                    "_start_project_context",
                    side_effect=RuntimeError("missing_service_start_command: autodetect_failed_backend"),
                ),
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(
                            ["--plan", "feature-a", "--omx", "--ultragoal", "--headless"],
                            env={"ENVCTL_DEFAULT_MODE": "trees"},
                        )
                    )

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Implementation session is running, but local app startup failed.", rendered)
            self.assertIn("attach: tmux attach -t omx-feature-session", rendered)
            self.assertIn("Local app startup:", rendered)
            self.assertNotIn("Startup failed:", rendered)

    def test_strict_truth_does_not_turn_degraded_plan_agent_handoff_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"ENVCTL_RUNTIME_TRUTH_MODE": "strict"})
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )
            attach_target = PlanAgentAttachTarget(
                repo_root=repo,
                session_name="envctl-feature-session",
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "envctl-feature-session"),
            )
            launch_result = PlanAgentLaunchResult(
                status="launched",
                reason="launched",
                outcomes=(
                    PlanAgentLaunchOutcome(
                        worktree_name=context.name,
                        worktree_root=Path(context.root),
                        surface_id=None,
                        status="launched",
                    ),
                ),
                attach_target=attach_target,
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals", return_value=launch_result),
                patch.object(
                    engine,
                    "_start_project_context",
                    side_effect=RuntimeError("missing_service_start_command: autodetect_failed_backend"),
                ),
                patch.object(engine, "_reconcile_state_truth", return_value=["feature-a-1 Backend"]) as reconcile_mock,
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(
                            ["--plan", "feature-a", "--tmux", "--headless"],
                            env={"ENVCTL_DEFAULT_MODE": "trees"},
                        )
                    )

            self.assertEqual(code, 0)
            reconcile_mock.assert_not_called()
            rendered = out.getvalue()
            self.assertIn("Implementation session is running, but local app startup failed.", rendered)
            self.assertNotIn("service truth degraded after startup", rendered)
            self.assertNotIn("Startup failed:", rendered)
            reconcile_events = [event for event in engine.events if event.get("event") == "state.reconcile"]
            self.assertTrue(reconcile_events)
            self.assertEqual(reconcile_events[-1].get("reason"), "plan_agent_handoff_degraded")
            self.assertTrue(reconcile_events[-1].get("skipped"))

    def test_plan_agent_launch_failed_keeps_startup_failure_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch(
                    "envctl_engine.startup.lifecycle.launch_plan_agent_terminals",
                    return_value=PlanAgentLaunchResult(status="failed", reason="missing_executables", outcomes=()),
                ),
                patch.object(
                    engine,
                    "_start_project_context",
                    side_effect=RuntimeError("missing_service_start_command: autodetect_failed_backend"),
                ),
                patch.object(engine, "_write_artifacts"),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(
                            ["--plan", "feature-a", "--tmux", "--headless"],
                            env={"ENVCTL_DEFAULT_MODE": "trees"},
                        )
                    )

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("Startup failed: Plan agent session failed to start", rendered)
            self.assertIn(f"{STATUS_FAILURE} Startup failed: Plan agent session failed to start", rendered)
            self.assertNotIn("Implementation session is running, but local app startup failed.", rendered)

    def test_startup_failure_final_status_colors_x_and_names_failed_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            engine.env["ENVCTL_UI_COLOR_MODE"] = "on"
            healthy_context = self._tree_context(
                repo,
                "refactoring_supportopia_to_pele_complete_repo_rename-1",
                "refactoring_supportopia_to_pele_complete_repo_rename/1",
                backend_port=8215,
                frontend_port=9215,
            )
            failing_context = self._tree_context(
                repo,
                "refactoring_repository_layout_cleanliness_consolidation-1",
                "refactoring_repository_layout_cleanliness_consolidation/1",
                backend_port=8204,
                frontend_port=9204,
            )

            failure = (
                "Failed to start refactoring_repository_layout_cleanliness_consolidation-1 backend on port 8204: "
                "backend listener not detected for refactoring_repository_layout_cleanliness_consolidation-1 "
                "on port 8204"
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[healthy_context, failing_context]),
                patch.object(engine, "_select_plan_projects", return_value=[healthy_context, failing_context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(
                        raw_projects=[],
                        selected_contexts=[healthy_context, failing_context],
                        created_worktrees=(),
                    ),
                ),
                patch.object(engine, "_start_project_context", side_effect=RuntimeError(failure)),
                patch.object(engine, "_write_artifacts"),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(
                            ["--plan", "--headless"],
                            env={"ENVCTL_DEFAULT_MODE": "trees"},
                        )
                    )

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("\033[31m✗\033[0m", rendered)
            self.assertIn("worktree: refactoring_repository_layout_cleanliness_consolidation-1", rendered)
            self.assertIn(
                "Startup failed: Failed to start refactoring_repository_layout_cleanliness_consolidation-1",
                rendered,
            )

    def test_plain_plan_without_ai_session_keeps_missing_service_command_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch.object(
                    engine,
                    "_start_project_context",
                    side_effect=RuntimeError("missing_service_start_command: autodetect_failed_backend"),
                ),
                patch.object(engine, "_write_artifacts"),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("Startup failed: missing_service_start_command: autodetect_failed_backend", rendered)
            self.assertNotIn("Implementation session is running, but local app startup failed.", rendered)
