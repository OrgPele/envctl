# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.startup.startup_orchestrator_flow_test_support import *


class StartupOrchestratorFlowHandoffTests(StartupOrchestratorFlowTestCase):
    def test_headless_plan_prints_attach_command_from_plan_agent_launch(self) -> None:
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
                new_session_command=(
                    "ENVCTL_USE_REPO_WRAPPER=1",
                    "/tmp/repo/bin/envctl",
                    "--plan",
                    "feature-a",
                    "--tmux",
                    "--opencode",
                    "--new-session",
                    "--headless",
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
                patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals", return_value=PlanAgentLaunchResult(status="launched", reason="launched", attach_target=attach_target)),
                patch.object(engine, "_write_artifacts"),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"}))

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertNotIn("session_id:", rendered)
            self.assertNotIn("run_id:", rendered)
            self.assertIn(
                "existing session: envctl did not create a new AI session because one already exists for this plan/workspace/CLI.",
                rendered,
            )
            self.assertIn("attach: tmux attach -t envctl-test-session", rendered)
            self.assertIn("new session: ENVCTL_USE_REPO_WRAPPER=1 /tmp/repo/bin/envctl --plan feature-a --tmux --opencode --new-session --headless", rendered)
            self.assertIn("kill: tmux kill-session -t envctl-test-session", rendered)

    def test_headless_plan_does_not_print_stale_attach_target_after_validation_failure(self) -> None:
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
                session_name="omx-stale-session",
                window_name="%42",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "omx-stale-session"),
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
            captured: dict[str, object] = {}

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch("envctl_engine.startup.lifecycle.launch_plan_agent_terminals", return_value=launch_result),
                patch.object(engine, "_write_artifacts", side_effect=lambda state, contexts, *, errors: captured.update({"state": state, "contexts": list(contexts), "errors": list(errors)})),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(
                            ["--plan", "feature-a", "--omx", "--codex", "--entire-system", "--headless"],
                            env={"ENVCTL_DEFAULT_MODE": "trees"},
                        )
                    )

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertNotIn("attach: tmux attach -t omx-stale-session", rendered)
            self.assertIn("Plan agent launch did not leave an attachable AI session.", rendered)
            self.assertIn("reason: attach_target_stale_after_launch", rendered)
            self.assertIn("recovery: ENVCTL_PLAN_AGENT_CODEX_CYCLES=2", rendered)
            self.assertIn(f"ENVCTL_USE_REPO_WRAPPER=1 {repo / 'bin' / 'envctl'} --plan feature-a --tmux", rendered)
            self.assertIn("--entire-system", rendered)
            self.assertIn("--headless", rendered)
            self.assertIn("--new-session", rendered)
            self.assertNotIn("--omx", rendered)
            state = cast(RunState, captured["state"])
            self.assertEqual(state.metadata["plan_agent_launch_status"], "failed")
            self.assertEqual(state.metadata["plan_agent_launch_reason"], "attach_target_stale_after_launch")
            self.assertFalse(state.metadata["implementation_session_running"])
            self.assertEqual(state.metadata["plan_agent_stale_session_name"], "omx-stale-session")
            self.assertEqual(state.metadata["plan_agent_stale_attach_command"], "tmux attach -t omx-stale-session")
            recovery_command = str(state.metadata["plan_agent_recovery_command"])
            self.assertIn("--tmux", recovery_command)
            self.assertIn("--entire-system", recovery_command)
            self.assertIn("--new-session", recovery_command)
            self.assertNotIn("--omx", recovery_command)
            self.assertNotIn("--ralph", recovery_command)
            self.assertNotIn("--ultragoal", recovery_command)
            self.assertNotIn("--team", recovery_command)
            self.assertNotIn("plan_agent_attach_command", state.metadata)

    def test_interactive_plan_resume_exact_attaches_plan_agent_instead_of_dashboard(self) -> None:
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
            existing_state = RunState(
                run_id="run-existing",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(Path(context.root) / "backend"),
                        pid=123,
                        requested_port=8200,
                        actual_port=8200,
                        status="running",
                    )
                },
                requirements={},
                metadata={"repo_scope_id": engine.config.runtime_scope_id},
            )
            dependency_result = type(
                "DependencyBootstrapResult",
                (),
                {
                    "backend": type("BackendDependency", (), {"manager": "poetry"})(),
                    "frontend": type("FrontendDependency", (), {"manager": "npm"})(),
                    "skipped": (),
                },
            )()
            resumed_routes: list[object] = []

            def _record_resume(route: object) -> int:
                resumed_routes.append(route)
                return 0

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch(
                    "envctl_engine.startup.lifecycle.prepare_project_dependencies",
                    return_value=dependency_result,
                ),
                patch(
                    "envctl_engine.startup.lifecycle.launch_plan_agent_terminals",
                    return_value=PlanAgentLaunchResult(
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
                    ),
                ),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_session_exists", return_value=True),
                patch("envctl_engine.planning.plan_agent.omx_transport._tmux_display_message_succeeds", return_value=(True, "%42")),
                patch(
                    "envctl_engine.startup.run_reuse_resolution.evaluate_run_reuse",
                    return_value=RunReuseDecision(
                        candidate_state=existing_state,
                        decision_kind="resume_exact",
                        reason="exact_match",
                        selected_projects=[{"name": context.name, "root": str(Path(context.root).resolve())}],
                        state_projects=[{"name": context.name, "root": str(Path(context.root).resolve())}],
                    ),
                ),
                patch.object(engine, "_resume", side_effect=_record_resume),
                patch("envctl_engine.startup.lifecycle.attach_plan_agent_terminal", return_value=0) as attach_mock,
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as dashboard_mock,
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--omx"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 0)
            attach_mock.assert_called_once_with(engine, attach_target)
            dashboard_mock.assert_not_called()
            self.assertEqual(len(resumed_routes), 1)
            resumed_route = resumed_routes[0]
            self.assertEqual(getattr(resumed_route, "command", ""), "resume")
            self.assertTrue(getattr(resumed_route, "flags", {}).get("batch"))
            self.assertEqual(getattr(resumed_route, "flags", {}).get("_resume_source_command"), "plan")

    def test_interactive_plan_opencode_without_tmux_launches_existing_worktree_and_attaches(self) -> None:
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
                session_name="envctl-opencode-session",
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "envctl-opencode-session"),
            )
            existing_state = RunState(
                run_id="run-existing",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(Path(context.root) / "backend"),
                        pid=123,
                        requested_port=8200,
                        actual_port=8200,
                        status="running",
                    )
                },
                requirements={},
                metadata={"repo_scope_id": engine.config.runtime_scope_id},
            )
            dependency_result = type(
                "DependencyBootstrapResult",
                (),
                {
                    "backend": type("BackendDependency", (), {"manager": "poetry"})(),
                    "frontend": type("FrontendDependency", (), {"manager": "npm"})(),
                    "skipped": (),
                },
            )()
            captured_launch_worktrees: list[list[str]] = []
            resumed_routes: list[object] = []
            spinner_calls: list[tuple[str, str, bool | None]] = []

            def _record_launch(
                _runtime: object,
                *,
                route: object,
                created_worktrees: tuple[CreatedPlanWorktree, ...],
            ) -> PlanAgentLaunchResult:
                _ = route
                captured_launch_worktrees.append([worktree.name for worktree in created_worktrees])
                if not created_worktrees:
                    return PlanAgentLaunchResult(status="skipped", reason="no_new_worktrees")
                return PlanAgentLaunchResult(
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

            def _record_resume(route: object) -> int:
                resumed_routes.append(route)
                return 0

            @contextmanager
            def _record_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
                _ = start_immediately
                spinner_calls.append(("start", message, enabled))

                class _SpinnerStub:
                    def update(self, message: str) -> None:
                        spinner_calls.append(("update", message, None))

                    def succeed(self, message: str) -> None:
                        spinner_calls.append(("succeed", message, None))

                    def fail(self, message: str) -> None:
                        spinner_calls.append(("fail", message, None))

                yield _SpinnerStub()

            with (
                patch.object(engine, "_discover_projects", return_value=[context]),
                patch.object(engine, "_select_plan_projects", return_value=[context]),
                patch.object(
                    engine.planning_worktree_orchestrator,
                    "last_plan_selection_result",
                    return_value=PlanSelectionResult(raw_projects=[], selected_contexts=[context], created_worktrees=()),
                ),
                patch(
                    "envctl_engine.startup.lifecycle.prepare_project_dependencies",
                    return_value=dependency_result,
                ),
                patch(
                    "envctl_engine.startup.lifecycle.launch_plan_agent_terminals",
                    side_effect=_record_launch,
                ),
                patch(
                    "envctl_engine.startup.run_reuse_resolution.evaluate_run_reuse",
                    return_value=RunReuseDecision(
                        candidate_state=existing_state,
                        decision_kind="resume_exact",
                        reason="exact_match",
                        selected_projects=[{"name": context.name, "root": str(Path(context.root).resolve())}],
                        state_projects=[{"name": context.name, "root": str(Path(context.root).resolve())}],
                    ),
                ),
                patch.object(engine, "_resume", side_effect=_record_resume),
                patch("envctl_engine.startup.lifecycle.attach_plan_agent_terminal", return_value=0) as attach_mock,
                patch.object(engine, "_run_interactive_dashboard_loop", return_value=0) as dashboard_mock,
                patch("envctl_engine.startup.lifecycle.spinner", side_effect=_record_spinner),
                patch("envctl_engine.startup.lifecycle.resolve_spinner_policy") as policy_mock,
            ):
                policy_mock.side_effect = lambda *_args, **_kwargs: type(
                    "_Policy",
                    (),
                    {
                        "mode": "on",
                        "enabled": True,
                        "reason": "",
                        "backend": "rich",
                        "min_ms": 120,
                        "verbose_events": False,
                    },
                )()
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--opencode"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 0)
            self.assertEqual(captured_launch_worktrees, [["feature-a-1"]])
            attach_mock.assert_called_once_with(engine, attach_target)
            dashboard_mock.assert_not_called()
            self.assertEqual(len(resumed_routes), 1)
            self.assertTrue(getattr(resumed_routes[0], "flags", {}).get("batch"))
            self.assertEqual(spinner_calls, [])

    def test_headless_plan_agent_handoff_prints_attach_when_local_startup_fails(self) -> None:
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
            captured: dict[str, object] = {}

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
                patch.object(
                    engine,
                    "_write_artifacts",
                    side_effect=lambda state, contexts, *, errors: captured.update(
                        {"state": state, "contexts": list(contexts), "errors": list(errors)}
                    ),
                ),
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
            rendered = out.getvalue()
            self.assertIn("Implementation session is running, but local app startup failed.", rendered)
            self.assertIn("AI session:", rendered)
            self.assertIn("attach: tmux attach -t envctl-feature-session", rendered)
            self.assertIn("kill: tmux kill-session -t envctl-feature-session", rendered)
            self.assertIn("Local app startup:", rendered)
            self.assertIn("project: feature-a-1", rendered)
            self.assertIn("missing_service_start_command: autodetect_failed_backend", rendered)
            self.assertNotIn("Startup failed:", rendered)
            state = cast(RunState, captured["state"])
            self.assertTrue(state.metadata["plan_agent_handoff_degraded"])
            self.assertTrue(state.metadata["implementation_session_running"])
            self.assertTrue(state.metadata["local_startup_failed"])
            self.assertEqual(state.metadata["plan_agent_session_name"], "envctl-feature-session")
            self.assertEqual(captured["errors"], [])
            launch_events = [event for event in engine.events if event.get("event") == "startup.plan_agent_launch_state"]
            self.assertTrue(launch_events)
            self.assertEqual(launch_events[-1].get("status"), "launched")
            self.assertTrue(launch_events[-1].get("implementation_session_running"))
            warning_events = [event for event in engine.events if event.get("event") == "startup.project.warning"]
            self.assertTrue(warning_events)
            self.assertEqual(warning_events[-1].get("reason"), "plan_agent_handoff_local_startup_failed")
            self.assertTrue(warning_events[-1].get("implementation_session_running"))
            degraded_events = [
                event for event in engine.events if event.get("event") == "startup.plan_agent_handoff.degraded"
            ]
            self.assertTrue(degraded_events)
            self.assertEqual(degraded_events[-1].get("reason"), "missing_service_start_command")
            self.assertEqual(degraded_events[-1].get("route_transport"), "tmux")

    def test_headless_cmux_plan_agent_handoff_prints_surface_guidance_when_local_startup_fails(self) -> None:
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
            launch_result = PlanAgentLaunchResult(
                status="launched",
                reason="launched",
                outcomes=(
                    PlanAgentLaunchOutcome(
                        worktree_name=context.name,
                        worktree_root=Path(context.root),
                        workspace_id="workspace:6",
                        surface_id="surface:74",
                        status="launched",
                    ),
                ),
            )
            captured: dict[str, object] = {}

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
                patch.object(
                    engine,
                    "_write_artifacts",
                    side_effect=lambda state, contexts, *, errors: captured.update(
                        {"state": state, "contexts": list(contexts), "errors": list(errors)}
                    ),
                ),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(
                            ["--plan", "feature-a", "--cmux", "--headless"],
                            env={"ENVCTL_DEFAULT_MODE": "trees"},
                        )
                    )

            self.assertEqual(code, 0)
            rendered = out.getvalue()
            self.assertIn("Implementation session is running, but local app startup failed.", rendered)
            self.assertIn("launch: launched via cmux", rendered)
            self.assertIn("workspace: workspace:6", rendered)
            self.assertIn("surface: surface:74 (feature-a-1)", rendered)
            self.assertIn("focus: cmux select-workspace --workspace workspace:6", rendered)
            self.assertNotIn("attach guidance unavailable for this launch transport", rendered)
            state = cast(RunState, captured["state"])
            self.assertEqual(state.metadata["plan_agent_launch_transport"], "cmux")
            self.assertEqual(state.metadata["plan_agent_cmux_workspace_ids"], ["workspace:6"])
            self.assertEqual(state.metadata["plan_agent_cmux_surface_ids"], ["surface:74"])
            self.assertEqual(
                state.metadata["plan_agent_cmux_focus_commands"],
                [
                    "cmux select-workspace --workspace workspace:6 && cmux move-surface "
                    "--workspace workspace:6 --surface surface:74 --focus true"
                ],
            )
            self.assertNotIn("plan_agent_attach_command", state.metadata)
            self.assertEqual(state.metadata["plan_agent_launch_outcomes"][0]["workspace_id"], "workspace:6")
            launch_events = [event for event in engine.events if event.get("event") == "startup.plan_agent_launch_state"]
            self.assertTrue(launch_events)
            self.assertEqual(launch_events[-1].get("route_transport"), "cmux")
            self.assertEqual(launch_events[-1].get("launched_surface_ids"), ["surface:74"])
            self.assertEqual(launch_events[-1].get("launched_workspace_ids"), ["workspace:6"])

    def test_headless_opencode_launch_failure_does_not_print_ready_attach_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = self._repo(root)
            runtime = root / "runtime"
            engine = self._engine(repo, runtime)
            context = self._tree_context(repo, "feature-a-1", "feature-a/1", backend_port=8200, frontend_port=9200)
            launch_result = PlanAgentLaunchResult(
                status="failed",
                reason="launch_failed",
                outcomes=(
                    PlanAgentLaunchOutcome(
                        worktree_name=context.name,
                        worktree_root=Path(context.root),
                        surface_id=None,
                        status="failed",
                        reason="opencode_ready_timeout: zsh: command not found: opencode",
                    ),
                ),
            )
            written_states: list[RunState] = []

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
                    return_value=ProjectStartupResult(
                        requirements=RequirementsResult(project=context.name, health="healthy"),
                        services={},
                        warnings=[],
                    ),
                ),
                patch.object(engine, "_write_artifacts", side_effect=lambda state, *_args, **_kwargs: written_states.append(state)),
                patch.object(engine, "_should_enter_post_start_interactive", return_value=False),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--tmux", "--opencode", "--headless"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("Plan agent session failed to start", rendered)
            self.assertIn("opencode_ready_timeout", rendered)
            self.assertNotIn("OpenCode AI session ready", rendered)
            self.assertNotIn("attach: tmux attach", rendered)
            self.assertEqual(len(written_states), 1)
            self.assertTrue(written_states[0].metadata["plan_agent_launch_failed"])
            self.assertEqual(written_states[0].metadata["plan_agent_launch_status"], "failed")

    def test_interactive_plan_agent_degraded_handoff_attempts_attach(self) -> None:
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
                session_name="envctl-feature-session",
                window_name="feature-a-1",
                attach_via="attach-session",
                attach_command=("tmux", "attach", "-t", "envctl-feature-session"),
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
                    return_value=PlanAgentLaunchResult(
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
                    ),
                ),
                patch.object(
                    engine,
                    "_start_project_context",
                    side_effect=RuntimeError("missing_service_start_command: autodetect_failed_backend"),
                ),
                patch.object(engine, "_write_artifacts"),
                patch("envctl_engine.startup.finalization.attach_plan_agent_terminal", return_value=0) as attach_mock,
                patch.object(engine, "_should_enter_post_start_interactive", return_value=True),
            ):
                out = StringIO()
                with redirect_stdout(out):
                    code = engine.dispatch(
                        parse_route(["--plan", "feature-a", "--tmux"], env={"ENVCTL_DEFAULT_MODE": "trees"})
                    )

            self.assertEqual(code, 0)
            attach_mock.assert_called_once()
            rendered = out.getvalue()
            self.assertIn("Implementation session is running, but local app startup failed.", rendered)
            self.assertNotIn("Startup failed:", rendered)
