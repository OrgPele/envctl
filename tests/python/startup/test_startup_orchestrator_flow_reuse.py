# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.startup.startup_orchestrator_flow_test_support import *


class StartupOrchestratorFlowReuseTests(StartupOrchestratorFlowTestCase):
    def test_disabled_startup_reopens_existing_dashboard_run_when_identity_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"MAIN_STARTUP_ENABLE": "false"})
            context = self._main_context(repo)
            metadata = startup_support.build_startup_identity_metadata(
                engine,
                runtime_mode="main",
                project_contexts=[context],
            )
            existing_state = RunState(
                run_id="run-dashboard",
                mode="main",
                services={},
                requirements={},
                metadata={
                    **metadata,
                    "dashboard_runs_disabled": True,
                    "repo_scope_id": engine.config.runtime_scope_id,
                },
            )
            saved_states: list[RunState] = []

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_try_load_existing_state", return_value=existing_state),
                patch.object(engine, "_write_artifacts", side_effect=AssertionError("fresh dashboard state should not be written")),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
                patch.object(
                    engine.state_repository,
                    "save_resume_state",
                    side_effect=lambda *, state, emit, runtime_map_builder: (
                        saved_states.append(state),
                        {},
                    )[1],
                ),
            ):
                code = engine.dispatch(parse_route([], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertEqual(len(saved_states), 1)
            self.assertEqual(saved_states[0].run_id, "run-dashboard")
            self.assertEqual(saved_states[0].services, {})
            self.assertEqual(saved_states[0].metadata.get("last_reuse_reason"), "resume_dashboard_exact")

    def test_disabled_startup_creates_fresh_dashboard_run_when_identity_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"MAIN_STARTUP_ENABLE": "false"})
            context = self._main_context(repo)
            old_engine = self._engine(repo, runtime, extra={"MAIN_STARTUP_ENABLE": "false", "BACKEND_DIR": "api"})
            metadata = startup_support.build_startup_identity_metadata(
                old_engine,
                runtime_mode="main",
                project_contexts=[context],
            )
            existing_state = RunState(
                run_id="run-dashboard",
                mode="main",
                services={},
                requirements={},
                metadata={
                    **metadata,
                    "dashboard_runs_disabled": True,
                    "repo_scope_id": engine.config.runtime_scope_id,
                },
            )
            captured: dict[str, object] = {}

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_try_load_existing_state", return_value=existing_state),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
                patch.object(
                    engine.state_repository,
                    "save_resume_state",
                    side_effect=AssertionError("dashboard resume should not be used"),
                ),
                patch.object(
                    engine,
                    "_write_artifacts",
                    side_effect=lambda state, contexts, *, errors: captured.update(
                        {"state": state, "contexts": list(contexts), "errors": list(errors)}
                    ),
                ),
            ):
                code = engine.dispatch(parse_route([], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            state = cast(RunState, captured["state"])
            self.assertNotEqual(state.run_id, "run-dashboard")
            self.assertTrue(state.metadata["dashboard_runs_disabled"])

    def test_existing_omx_plan_session_summary_reuses_selected_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"TREES_STARTUP_ENABLE": "false"})
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
                new_session_command=(
                    "ENVCTL_USE_REPO_WRAPPER=1",
                    "/tmp/repo/bin/envctl",
                    "--plan",
                    "feature-a",
                    "--omx",
                    "--codex",
                    "--new-session",
                    "--headless",
                ),
            )
            captured_created_worktrees: list[list[str]] = []

            def _record_launch(_runtime: object, *, route: object, created_worktrees: tuple[CreatedPlanWorktree, ...]):
                _ = route
                captured_created_worktrees.append([item.name for item in created_worktrees])
                return PlanAgentLaunchResult(status="launched", reason="launched", attach_target=attach_target)

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals", side_effect=_record_launch),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_display_message_succeeds", return_value=(True, "%42")),
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(parse_route(["--plan", "feature-a", "--omx", "--codex", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"}))

            self.assertEqual(code, 0)
            self.assertEqual(captured_created_worktrees, [["feature-a-1"]])
            rendered = out.getvalue()
            self.assertIn(
                "existing session: envctl did not create a new AI session because one already exists for this plan/workspace/CLI.",
                rendered,
            )
            self.assertIn("attach: tmux attach -t omx-feature-session", rendered)
            self.assertIn("new session: ENVCTL_USE_REPO_WRAPPER=1 /tmp/repo/bin/envctl --plan feature-a --omx --codex --new-session --headless", rendered)
            self.assertIn("kill: tmux kill-session -t omx-feature-session", rendered)

    def test_explicit_cmux_plan_launch_reuses_selected_existing_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"TREES_STARTUP_ENABLE": "false"})
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )
            captured_created_worktrees: list[list[str]] = []

            def _record_launch(_runtime: object, *, route: object, created_worktrees: tuple[CreatedPlanWorktree, ...]):
                captured_created_worktrees.append([item.name for item in created_worktrees])
                self.assertTrue(getattr(route, "flags", {}).get("cmux"))
                self.assertFalse(getattr(route, "flags", {}).get("tmux"))
                return PlanAgentLaunchResult(
                    status="launched",
                    reason="launched",
                    outcomes=(
                        PlanAgentLaunchOutcome(
                            worktree_name=context.name,
                            worktree_root=Path(context.root),
                            surface_id="surface:1",
                            status="launched",
                        ),
                    ),
                )

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals", side_effect=_record_launch),
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                code = engine.dispatch(parse_route(["--plan", "feature-a", "--cmux", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"}))

            self.assertEqual(code, 0)
            self.assertEqual(captured_created_worktrees, [["feature-a-1"]])

    def test_resume_dashboard_exact_headless_plan_prints_attach_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"TREES_STARTUP_ENABLE": "false"})
            context = self._tree_context(
                repo,
                "feature-a-1",
                "feature-a/1",
                backend_port=8200,
                frontend_port=9200,
            )
            attach_target = PlanAgentAttachTarget(
                repo_root=repo,
                session_name="envctl-test-session",
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "envctl-test-session"),
            )
            existing_state = RunState(
                run_id="run-dashboard",
                mode="trees",
                services={},
                requirements={},
                metadata={"repo_scope_id": engine.config.runtime_scope_id},
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
                    return_value=PlanAgentLaunchResult(status="failed", reason="existing", attach_target=attach_target),
                ),
                patch(
                    "envctl_engine.startup.run_reuse_resolution.evaluate_run_reuse",
                    return_value=RunReuseDecision(
                        candidate_state=existing_state,
                        decision_kind="resume_dashboard_exact",
                        reason="exact_match",
                        selected_projects=[{"name": context.name, "root": str(Path(context.root).resolve())}],
                        state_projects=[{"name": context.name, "root": str(Path(context.root).resolve())}],
                    ),
                ),
                patch.object(engine.state_repository, "save_resume_state", return_value={}),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertNotIn("Planning mode complete; skipping service startup", rendered)
            self.assertIn("attach: tmux attach -t envctl-test-session", rendered)
            self.assertIn("kill: tmux kill-session -t envctl-test-session", rendered)

    def test_resume_reuse_failure_falls_back_to_fresh_run_id_before_failure_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            context = self._main_context(repo)
            metadata = startup_support.build_startup_identity_metadata(
                engine,
                runtime_mode="main",
                project_contexts=[context],
            )
            existing_state = RunState(
                run_id="run-existing",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        pid=1111,
                        requested_port=8000,
                        actual_port=8000,
                        status="running",
                    )
                },
                metadata=metadata,
            )
            captured: dict[str, object] = {}

            out = StringIO()
            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_try_load_existing_state", return_value=existing_state),
                patch.object(engine, "_resume", return_value=1),
                patch.object(engine, "_new_run_id", return_value="run-fresh-after-resume-failure"),
                patch.object(engine, "_start_project_context", side_effect=RuntimeError("fresh startup failed")),
                patch.object(
                    engine,
                    "_write_artifacts",
                    side_effect=lambda state, contexts, *, errors: captured.update(
                        {"state": state, "contexts": list(contexts), "errors": list(errors)}
                    ),
                ),
                redirect_stdout(out),
            ):
                code = engine.dispatch(parse_route(["start", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 1)
            written_state = cast(RunState, captured["state"])
            self.assertEqual(written_state.run_id, "run-fresh-after-resume-failure")
            self.assertNotEqual(written_state.run_id, existing_state.run_id)

    def test_reuse_expand_failure_writes_failed_state_to_fresh_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"ENVCTL_DEFAULT_MODE": "trees"})
            context_a = self._tree_context(repo, "feature-a-1", "feature-a/1", backend_port=8100, frontend_port=9100)
            context_b = self._tree_context(repo, "feature-b-1", "feature-b/1", backend_port=8200, frontend_port=9200)
            metadata = startup_support.build_startup_identity_metadata(
                engine,
                runtime_mode="trees",
                project_contexts=[context_a],
            )
            existing_state = RunState(
                run_id="run-existing-expand",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(Path(context_a.root) / "backend"),
                        pid=1111,
                        requested_port=8100,
                        actual_port=8100,
                        status="running",
                    )
                },
                metadata=metadata,
            )
            captured: dict[str, object] = {}

            with (
                patch.object(engine, "_discover_projects", return_value=[context_a, context_b]),
                patch.object(engine, "_select_plan_projects", return_value=[context_a, context_b]),
                patch(
                    "envctl_engine.startup.run_reuse_resolution.evaluate_run_reuse",
                    return_value=RunReuseDecision(
                        candidate_state=existing_state,
                        decision_kind="reuse_expand",
                        reason="expand_match",
                        selected_projects=[
                            {"name": "feature-a-1", "root": str(Path(context_a.root).resolve())},
                            {"name": "feature-b-1", "root": str(Path(context_b.root).resolve())},
                        ],
                        state_projects=[{"name": "feature-a-1", "root": str(Path(context_a.root).resolve())}],
                    ),
                ),
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                patch.object(engine, "_new_run_id", return_value="run-fresh-expand-failure"),
                patch.object(engine, "_start_project_context", side_effect=RuntimeError("new project startup failed")),
                patch.object(
                    engine,
                    "_write_artifacts",
                    side_effect=lambda state, contexts, *, errors: captured.update(
                        {"state": state, "contexts": list(contexts), "errors": list(errors)}
                    ),
                ),
            ):
                code = engine.dispatch(parse_route(["--plan", "feature-a,feature-b", "--batch"], env={}))

            self.assertEqual(code, 1)
            written_state = cast(RunState, captured["state"])
            self.assertEqual(written_state.run_id, "run-fresh-expand-failure")
            self.assertNotEqual(written_state.run_id, existing_state.run_id)

    def test_tree_start_reuse_expand_preserves_existing_services_and_starts_only_new_tree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime, extra={"ENVCTL_DEFAULT_MODE": "trees"})
            context_a = self._tree_context(repo, "feature-a-1", "feature-a/1", backend_port=8100, frontend_port=9100)
            context_b = self._tree_context(repo, "feature-b-1", "feature-b/1", backend_port=8200, frontend_port=9200)
            metadata = startup_support.build_startup_identity_metadata(
                engine,
                runtime_mode="trees",
                project_contexts=[context_a],
            )
            existing_state = RunState(
                run_id="run-existing-expand",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(Path(context_a.root) / "backend"),
                        pid=1111,
                        requested_port=8100,
                        actual_port=8100,
                        status="running",
                    )
                },
                metadata=metadata,
            )
            captured: dict[str, object] = {}
            started: list[str] = []

            def _start_context(context: object, **_kwargs: object) -> ProjectStartupResult:
                name = str(getattr(context, "name", ""))
                started.append(name)
                self.assertEqual(name, "feature-b-1")
                return ProjectStartupResult(
                    requirements=RequirementsResult(project=name, health="healthy"),
                    services={
                        "feature-b-1 Backend": ServiceRecord(
                            name="feature-b-1 Backend",
                            type="backend",
                            cwd=str(Path(getattr(context, "root")) / "backend"),
                            pid=2222,
                            requested_port=8200,
                            actual_port=8200,
                            status="running",
                        )
                    },
                    warnings=[],
                )

            with (
                patch.object(engine, "_discover_projects", return_value=[context_a, context_b]),
                patch.object(engine, "_try_load_existing_state", return_value=existing_state),
                patch.object(engine, "_reconcile_state_truth", return_value=[]),
                patch.object(engine, "_start_project_context", side_effect=_start_context),
                patch.object(engine, "_terminate_services_from_state") as terminate_mock,
                patch.object(startup_lifecycle, "terminate_restart_orphan_listeners_with_runtime") as orphan_mock,
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
                patch.object(
                    engine,
                    "_write_artifacts",
                    side_effect=lambda state, contexts, *, errors: captured.update(
                        {"state": state, "contexts": list(contexts), "errors": list(errors)}
                    ),
                ),
            ):
                code = engine.dispatch(
                    parse_route(
                        ["--trees", "--project", "feature-a-1", "--project", "feature-b-1", "--batch"],
                        env={},
                    )
                )

            self.assertEqual(code, 0)
            self.assertEqual(started, ["feature-b-1"])
            terminate_mock.assert_not_called()
            orphan_mock.assert_not_called()
            written_state = cast(RunState, captured["state"])
            self.assertEqual(set(written_state.services), {"feature-a-1 Backend", "feature-b-1 Backend"})
            self.assertEqual(captured["errors"], [])
