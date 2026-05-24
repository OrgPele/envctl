# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.runtime.lifecycle_parity_test_support import *


class LifecycleModeScopeParityTests(unittest.TestCase):
    def test_restart_prefers_requested_mode_when_loading_previous_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})

            main_state = RunState(run_id="run-main", mode="main")
            trees_state = RunState(run_id="run-trees", mode="trees")
            seen_lookup_modes: list[str | None] = []
            seen_discovery_modes: list[str] = []

            def fake_load_state(*, mode: str | None = None):
                seen_lookup_modes.append(mode)
                if mode == "trees":
                    return trees_state
                return main_state

            def fake_discover_projects(*, mode: str):
                seen_discovery_modes.append(mode)
                return []

            engine._try_load_existing_state = fake_load_state  # type: ignore[method-assign]
            engine._discover_projects = fake_discover_projects  # type: ignore[method-assign]

            code = engine.dispatch(parse_route(["--restart", "--tree", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertEqual(seen_lookup_modes, ["trees"])
            self.assertEqual(seen_discovery_modes, ["trees"])

    def test_restart_setup_worktrees_uses_effective_trees_mode_for_state_lookup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})

            main_state = RunState(run_id="run-main", mode="main")
            trees_state = RunState(run_id="run-trees", mode="trees")
            seen_lookup_modes: list[str | None] = []
            seen_discovery_modes: list[str] = []

            def fake_load_state(*, mode: str | None = None):
                seen_lookup_modes.append(mode)
                if mode == "trees":
                    return trees_state
                return main_state

            def fake_discover_projects(*, mode: str):
                seen_discovery_modes.append(mode)
                return []

            engine._try_load_existing_state = fake_load_state  # type: ignore[method-assign]
            engine._discover_projects = fake_discover_projects  # type: ignore[method-assign]

            code = engine.dispatch(
                parse_route(
                    ["--restart", "--setup-worktrees", "feature-a", "1", "--batch"],
                    env={},
                )
            )

            self.assertEqual(code, 1)
            self.assertEqual(seen_lookup_modes, ["trees"])
            self.assertEqual(seen_discovery_modes, ["trees"])

    def test_restart_preserves_effective_mode_when_loaded_state_mode_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})

            mismatched_state = RunState(run_id="run-trees", mode="trees")
            seen_lookup_modes: list[str | None] = []
            seen_discovery_modes: list[str] = []

            def fake_load_state(*, mode: str | None = None):
                seen_lookup_modes.append(mode)
                return mismatched_state

            def fake_discover_projects(*, mode: str):
                seen_discovery_modes.append(mode)
                return []

            engine._try_load_existing_state = fake_load_state  # type: ignore[method-assign]
            engine._discover_projects = fake_discover_projects  # type: ignore[method-assign]

            code = engine.dispatch(parse_route(["--restart", "--main", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertEqual(seen_lookup_modes, ["main"])
            self.assertEqual(seen_discovery_modes, ["main"])

    def test_restart_does_not_terminate_cross_mode_loaded_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})

            mismatched_state = RunState(
                run_id="run-trees",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(repo / "trees" / "feature-a" / "1" / "backend"),
                        pid=12345,
                        requested_port=8020,
                        actual_port=8020,
                        status="running",
                    )
                },
            )
            terminate_calls: list[str] = []
            seen_discovery_modes: list[str] = []

            engine._try_load_existing_state = (  # type: ignore[method-assign]
                lambda mode=None, strict_mode_match=False: mismatched_state
            )
            engine._terminate_services_from_state = (  # type: ignore[method-assign]
                lambda state, selected_services, aggressive, verify_ownership: terminate_calls.append(state.mode)
            )

            def fake_discover_projects(*, mode: str):
                seen_discovery_modes.append(mode)
                return []

            engine._discover_projects = fake_discover_projects  # type: ignore[method-assign]

            code = engine.dispatch(parse_route(["--restart", "--main", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertEqual(seen_discovery_modes, ["main"])
            self.assertEqual(terminate_calls, [])

    def test_start_blocks_when_mode_startup_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "MAIN_STARTUP_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            engine._discover_projects = lambda **_kwargs: self.fail("project discovery should not run")  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["start"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("envctl runs are disabled for main in .envctl", out.getvalue())

    def test_restart_blocks_when_mode_startup_is_disabled_before_prestop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "MAIN_STARTUP_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            engine._try_load_existing_state = lambda **_kwargs: self.fail("state lookup should not run")  # type: ignore[assignment]
            engine._terminate_services_from_state = lambda *args, **kwargs: self.fail("pre-stop should not run")  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--restart", "--main", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("envctl runs are disabled for main in .envctl", out.getvalue())

    def test_resume_blocks_when_mode_startup_is_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "MAIN_STARTUP_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            engine._try_load_existing_state = lambda **_kwargs: RunState(run_id="run-main", mode="main")  # type: ignore[assignment]
            engine._reconcile_state_truth = lambda _state: self.fail("reconcile should not run")  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--resume", "--main", "--batch"], env={}))

            self.assertEqual(code, 1)
            self.assertIn("envctl runs are disabled for main in .envctl", out.getvalue())

    def test_plan_allows_worktree_setup_when_mode_runs_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "TREES_STARTUP_ENABLE": "false",
                    "ENVCTL_DEFAULT_MODE": "trees",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            seen_modes: list[str] = []

            def fake_discover_projects(*, mode: str):  # noqa: ANN202
                seen_modes.append(mode)
                return []

            engine._discover_projects = fake_discover_projects  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--plan", "--batch"], env={"ENVCTL_DEFAULT_MODE": "trees"}))

            self.assertEqual(code, 1)
            self.assertEqual(seen_modes, ["trees"])
            self.assertNotIn("envctl runs are disabled for trees in .envctl", out.getvalue())
            self.assertIn("No projects discovered for selected mode.", out.getvalue())

    def test_plan_skips_service_startup_when_mode_runs_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "TREES_STARTUP_ENABLE": "false",
                    "ENVCTL_DEFAULT_MODE": "trees",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            context = ProjectContext(
                name="feature-a-1",
                root=repo / "trees" / "feature-a-1",
                ports={
                    "backend": PortPlan("feature-a-1", 8000, 8000, 8000, "requested"),
                    "frontend": PortPlan("feature-a-1", 9000, 9000, 9000, "requested"),
                    "db": PortPlan("feature-a-1", 5432, 5432, 5432, "requested"),
                    "redis": PortPlan("feature-a-1", 6379, 6379, 6379, "requested"),
                    "n8n": PortPlan("feature-a-1", 5678, 5678, 5678, "requested"),
                },
            )
            engine._discover_projects = lambda **_kwargs: [context]  # type: ignore[assignment]
            engine._select_plan_projects = lambda route, contexts: contexts  # type: ignore[assignment]
            engine._start_project_context = lambda **_kwargs: self.fail("project startup should not run")  # type: ignore[assignment]
            engine._try_load_existing_state = lambda **_kwargs: None  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--plan", "--batch"], env={"ENVCTL_DEFAULT_MODE": "trees"}))

            self.assertEqual(code, 0)
            self.assertIn(
                "Planning mode complete; skipping service startup because envctl runs are disabled for trees.",
                out.getvalue(),
            )

    def test_implicit_start_opens_dashboard_when_main_runs_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "MAIN_STARTUP_ENABLE": "false",
                    "ENVCTL_DEFAULT_MODE": "main",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            context = ProjectContext(
                name="Main",
                root=repo,
                ports={
                    "backend": PortPlan("Main", 8000, 8000, 8000, "requested"),
                    "frontend": PortPlan("Main", 9000, 9000, 9000, "requested"),
                },
            )
            engine._discover_projects = lambda **_kwargs: [context]  # type: ignore[assignment]
            engine._start_project_context = lambda **_kwargs: self.fail("project startup should not run")  # type: ignore[assignment]
            engine._try_load_existing_state = lambda **_kwargs: None  # type: ignore[assignment]
            engine._write_artifacts = lambda *_args, **_kwargs: None  # type: ignore[assignment]
            engine._should_enter_post_start_interactive = lambda _route: True  # type: ignore[assignment]

            seen_state: list[RunState] = []

            def fake_dashboard_loop(state: RunState) -> int:
                seen_state.append(state)
                return 0

            engine._run_interactive_dashboard_loop = fake_dashboard_loop  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--main"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            self.assertNotIn("opening dashboard without starting services", out.getvalue())
            self.assertEqual(len(seen_state), 1)
            self.assertEqual(seen_state[0].mode, "main")
            self.assertEqual(seen_state[0].metadata.get("dashboard_configured_service_types"), ["backend", "frontend"])

    def test_dashboard_reopen_uses_same_run_id_but_fresh_session_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "MAIN_STARTUP_ENABLE": "false",
                    "ENVCTL_DEFAULT_MODE": "main",
                }
            )
            context = ProjectContext(
                name="Main",
                root=repo,
                ports={
                    "backend": PortPlan("Main", 8000, 8000, 8000, "requested"),
                    "frontend": PortPlan("Main", 9000, 9000, 9000, "requested"),
                },
            )
            first_engine = PythonEngineRuntime(config, env={})
            metadata = startup_support.build_startup_identity_metadata(
                first_engine,
                runtime_mode="main",
                project_contexts=[context],
            )
            first_engine.state_repository.save_resume_state(
                state=RunState(
                    run_id="run-dashboard",
                    mode="main",
                    services={},
                    requirements={},
                    metadata={
                        **metadata,
                        "dashboard_runs_disabled": True,
                        "repo_scope_id": config.runtime_scope_id,
                    },
                ),
                emit=lambda *args, **kwargs: None,
                runtime_map_builder=lambda _state: {},
            )
            second_engine = PythonEngineRuntime(config, env={})
            second_engine._discover_projects = lambda **_kwargs: [context]  # type: ignore[assignment]
            second_engine._should_enter_post_start_interactive = lambda _route: False  # type: ignore[assignment]

            out = StringIO()
            with redirect_stdout(out):
                code = second_engine.dispatch(parse_route(["--batch"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            latest = second_engine.state_repository.load_latest(mode="main", strict_mode_match=True)
            self.assertIsNotNone(latest)
            assert latest is not None
            self.assertEqual(latest.run_id, "run-dashboard")
            self.assertEqual(latest.metadata.get("last_reuse_reason"), "resume_dashboard_exact")
            rendered = out.getvalue()
            self.assertNotIn("Resumed run_id=", rendered)
            self.assertIn("run-dashboard", rendered)
            self.assertIn("session_id:", rendered)

    def test_explicit_start_still_blocks_when_main_runs_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "MAIN_STARTUP_ENABLE": "false",
                    "ENVCTL_DEFAULT_MODE": "main",
                }
            )
            engine = PythonEngineRuntime(config, env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["start", "--main", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 1)
            self.assertIn("envctl runs are disabled for main in .envctl", out.getvalue())
