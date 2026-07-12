# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.startup.startup_spinner_integration_test_support import *


class StartupRestartServiceScopeTests(StartupSpinnerIntegrationTestCase):
    def test_restart_service_only_preserves_other_services_and_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "echo backend",
                    "ENVCTL_FRONTEND_START_CMD": "echo frontend",
                    "ENVCTL_UI_SPINNER_MODE": "off",
                },
            )
            previous_state = RunState(
                run_id="run-old",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        pid=11111,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo / "frontend"),
                        requested_port=9000,
                        actual_port=9000,
                        pid=22222,
                        status="running",
                    ),
                },
                requirements={
                    "Main": RequirementsResult(
                        project="Main",
                        db={"requested": 5432, "final": 5432, "retries": 0, "success": True, "enabled": True},
                        redis={"requested": 6379, "final": 6379, "retries": 0, "success": True, "enabled": False},
                        n8n={"requested": 5678, "final": 5678, "retries": 0, "success": True, "enabled": False},
                        supabase={"requested": 5432, "final": 5432, "retries": 0, "success": True, "enabled": False},
                        health="healthy",
                    )
                },
            )
            context = ProjectContext(
                name="Main",
                root=repo,
                ports={
                    "backend": PortPlan("Main", 8000, 8000, 8000, "requested"),
                    "frontend": PortPlan("Main", 9000, 9000, 9000, "requested"),
                    "db": PortPlan("Main", 5432, 5432, 5432, "requested"),
                    "redis": PortPlan("Main", 6379, 6379, 6379, "requested"),
                    "n8n": PortPlan("Main", 5678, 5678, 5678, "requested"),
                },
            )

            terminate_calls: list[set[str] | None] = []
            release_calls: list[str] = []
            captured_state: dict[str, RunState] = {}

            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: previous_state  # type: ignore[method-assign]
            engine._discover_projects = lambda mode: [context]  # type: ignore[method-assign]
            engine._reserve_project_ports = lambda _context, route=None: None  # type: ignore[method-assign]
            engine._terminate_services_from_state = (  # type: ignore[method-assign]
                lambda state, selected_services, aggressive, verify_ownership: (
                    terminate_calls.append(selected_services) or set()
                )
            )
            engine._release_requirement_ports = (  # type: ignore[method-assign]
                lambda _requirements: release_calls.append("released")
            )
            engine._start_project_context = (  # type: ignore[method-assign]
                lambda context, mode, route, run_id: ProjectStartupResult(
                    requirements=previous_state.requirements["Main"],
                    services={
                        "Main Backend": ServiceRecord(
                            name="Main Backend",
                            type="backend",
                            cwd=str(repo / "backend"),
                            requested_port=8000,
                            actual_port=8000,
                            pid=33333,
                            status="running",
                        )
                    },
                    warnings=[],
                )
            )
            engine._write_artifacts = (  # type: ignore[method-assign]
                lambda run_state, contexts, errors=None: captured_state.setdefault("state", run_state)
            )

            route = parse_route(["--restart", "Main", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"})
            route.flags.update(
                {
                    "services": ["Main Backend"],
                    "restart_service_types": ["backend"],
                    "restart_include_requirements": False,
                }
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(terminate_calls, [{"Main Backend"}])
            self.assertEqual(release_calls, [])
            run_state = captured_state["state"]
            self.assertIn("Main Backend", run_state.services)
            self.assertIn("Main Frontend", run_state.services)
            self.assertEqual(run_state.services["Main Backend"].pid, 33333)
            self.assertEqual(run_state.services["Main Frontend"].pid, 22222)
            self.assertIn("Main", run_state.requirements)
            merge_events = [
                event for event in engine.events if event.get("event") == "runtime.state.merge_preserved_services"
            ]
            self.assertEqual(len(merge_events), 1)
            self.assertEqual(merge_events[0]["preserved_services"], ["Main Frontend"])
            self.assertEqual(merge_events[0]["replaced_services"], ["Main Backend"])

    def test_restart_stopped_service_starts_it_without_terminating_running_sibling(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "echo backend",
                    "ENVCTL_FRONTEND_START_CMD": "echo frontend",
                    "ENVCTL_UI_SPINNER_MODE": "off",
                },
            )
            previous_requirements = RequirementsResult(
                project="Main",
                db={"requested": 5432, "final": 5432, "retries": 0, "success": True, "enabled": False},
                redis={"requested": 6379, "final": 6379, "retries": 0, "success": True, "enabled": False},
                n8n={"requested": 5678, "final": 5678, "retries": 0, "success": True, "enabled": False},
                supabase={"requested": 5432, "final": 5432, "retries": 0, "success": True, "enabled": False},
                health="healthy",
            )
            previous_state = RunState(
                run_id="run-old",
                mode="main",
                services={
                    "Main Backend": ServiceRecord(
                        name="Main Backend",
                        type="backend",
                        cwd=str(repo / "backend"),
                        requested_port=8000,
                        actual_port=8000,
                        pid=11111,
                        status="running",
                    ),
                },
                requirements={"Main": previous_requirements},
                metadata={
                    "project_roots": {"Main": str(repo)},
                    "dashboard_stopped_services": [
                        {"name": "Main Frontend", "project": "Main", "type": "frontend"},
                    ],
                    "dashboard_configured_service_types": ["backend", "frontend"],
                },
            )
            context = ProjectContext(
                name="Main",
                root=repo,
                ports={
                    "backend": PortPlan("Main", 8000, 8000, 8000, "requested"),
                    "frontend": PortPlan("Main", 9000, 9000, 9000, "requested"),
                    "db": PortPlan("Main", 5432, 5432, 5432, "requested"),
                    "redis": PortPlan("Main", 6379, 6379, 6379, "requested"),
                    "n8n": PortPlan("Main", 5678, 5678, 5678, "requested"),
                },
            )

            terminate_calls: list[set[str] | None] = []
            captured_state: dict[str, RunState] = {}

            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: previous_state  # type: ignore[method-assign]
            engine._discover_projects = lambda mode: [context]  # type: ignore[method-assign]
            engine._reserve_project_ports = lambda _context, route=None: None  # type: ignore[method-assign]
            engine._terminate_services_from_state = (  # type: ignore[method-assign]
                lambda state, selected_services, aggressive, verify_ownership: (
                    terminate_calls.append(selected_services) or set()
                )
            )
            engine._release_requirement_ports = (  # type: ignore[method-assign]
                lambda _requirements: self.fail("requirements should be preserved for stopped service restart")
            )

            def start_project_context(*, context, mode, route, run_id):  # noqa: ANN001
                self.assertTrue(bool(route.flags.get("_restart_request")))
                self.assertEqual(route.flags.get("services"), ["Main Frontend"])
                self.assertEqual(route.flags.get("restart_service_types"), ["frontend"])
                return ProjectStartupResult(
                    requirements=previous_requirements,
                    services={
                        "Main Frontend": ServiceRecord(
                            name="Main Frontend",
                            type="frontend",
                            cwd=str(repo / "frontend"),
                            requested_port=9000,
                            actual_port=9000,
                            pid=44444,
                            status="running",
                        )
                    },
                    warnings=[],
                )

            engine._start_project_context = start_project_context  # type: ignore[method-assign]
            engine._write_artifacts = (  # type: ignore[method-assign]
                lambda run_state, contexts, errors=None: captured_state.setdefault("state", run_state)
            )

            route = parse_route(["--restart", "Main", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"})
            route.flags.update(
                {
                    "services": ["Main Frontend"],
                    "restart_service_types": ["frontend"],
                    "restart_include_requirements": False,
                }
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(terminate_calls, [set()])
            run_state = captured_state["state"]
            self.assertEqual(run_state.services["Main Backend"].pid, 11111)
            self.assertEqual(run_state.services["Main Frontend"].pid, 44444)
            self.assertNotIn("dashboard_stopped_services", run_state.metadata)

    def test_restart_service_only_preserves_shared_tree_dependency_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            worktree = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (worktree / "backend").mkdir(parents=True, exist_ok=True)
            (worktree / "frontend").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "true",
                    "N8N_ENABLE": "true",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "ENVCTL_DEPENDENCY_SCOPE": "shared",
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "echo backend",
                    "ENVCTL_FRONTEND_START_CMD": "echo frontend",
                    "ENVCTL_UI_SPINNER_MODE": "off",
                },
            )
            previous_requirements = RequirementsResult(
                project="Main",
                redis={"requested": 6379, "final": 6485, "retries": 0, "success": True, "enabled": True},
                n8n={"requested": 5678, "final": 5784, "retries": 0, "success": True, "enabled": True},
                supabase={"requested": 5432, "final": 0, "retries": 0, "success": False, "enabled": True},
                health="healthy",
            )
            previous_state = RunState(
                run_id="run-old",
                mode="trees",
                services={
                    "feature-a-1 Backend": ServiceRecord(
                        name="feature-a-1 Backend",
                        type="backend",
                        cwd=str(worktree / "backend"),
                        requested_port=8101,
                        actual_port=8101,
                        pid=11111,
                        status="running",
                    ),
                    "feature-a-1 Frontend": ServiceRecord(
                        name="feature-a-1 Frontend",
                        type="frontend",
                        cwd=str(worktree / "frontend"),
                        requested_port=9101,
                        actual_port=9101,
                        pid=22222,
                        status="running",
                    ),
                },
                requirements={"feature-a-1": previous_requirements},
                metadata={
                    "project_roots": {"feature-a-1": str(worktree), "Main": str(repo)},
                    "dependency_mode": "shared",
                    "shared_dependencies": True,
                    "dashboard_dependency_scope": "shared",
                    "dashboard_shared_dependency_project": "Main",
                },
            )
            context = ProjectContext(
                name="feature-a-1",
                root=worktree,
                ports={
                    "backend": PortPlan("feature-a-1", 8101, 8101, 8101, "requested"),
                    "frontend": PortPlan("feature-a-1", 9101, 9101, 9101, "requested"),
                    "db": PortPlan("feature-a-1", 5432, 5432, 5432, "requested"),
                    "redis": PortPlan("feature-a-1", 6485, 6485, 6485, "requested"),
                    "n8n": PortPlan("feature-a-1", 5784, 5784, 5784, "requested"),
                    "supabase": PortPlan("feature-a-1", 54322, 54322, 54322, "requested"),
                },
            )

            terminate_calls: list[set[str] | None] = []
            captured_state: dict[str, RunState] = {}

            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: previous_state  # type: ignore[method-assign]
            engine._discover_projects = lambda mode: [context]  # type: ignore[method-assign]
            engine._reserve_project_ports = lambda _context, route=None: None  # type: ignore[method-assign]
            engine._terminate_services_from_state = (  # type: ignore[method-assign]
                lambda state, selected_services, aggressive, verify_ownership: (
                    terminate_calls.append(selected_services) or set()
                )
            )
            engine._release_requirement_ports = (  # type: ignore[method-assign]
                lambda _requirements: self.fail("shared requirements should be preserved for app-only restart")
            )

            def start_project_context(*, context, mode, route, run_id):  # noqa: ANN001
                _ = context, mode, run_id
                self.assertTrue(bool(route.flags.get("_restart_request")))
                self.assertFalse(bool(route.flags.get("_restart_include_requirements")))
                self.assertEqual(route.flags.get("restart_service_types"), ["backend"])
                return ProjectStartupResult(
                    requirements=previous_requirements,
                    services={
                        "feature-a-1 Backend": ServiceRecord(
                            name="feature-a-1 Backend",
                            type="backend",
                            cwd=str(worktree / "backend"),
                            requested_port=8101,
                            actual_port=8101,
                            pid=33333,
                            status="running",
                        )
                    },
                    warnings=[],
                )

            engine._start_project_context = start_project_context  # type: ignore[method-assign]
            engine._write_artifacts = (  # type: ignore[method-assign]
                lambda run_state, contexts, errors=None: captured_state.setdefault("state", run_state)
            )

            route = parse_route(["--restart", "feature-a-1", "--trees", "--batch"], env={})
            route.flags.update(
                {
                    "services": ["feature-a-1 Backend"],
                    "restart_service_types": ["backend"],
                    "restart_include_requirements": False,
                }
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(terminate_calls, [{"feature-a-1 Backend"}])
            run_state = captured_state["state"]
            self.assertEqual(run_state.metadata.get("dependency_mode"), "shared")
            self.assertTrue(run_state.metadata.get("shared_dependencies"))
            self.assertEqual(run_state.metadata.get("dashboard_dependency_scope"), "shared")
            self.assertEqual(run_state.metadata.get("dashboard_shared_dependency_project"), "Main")
            self.assertEqual(run_state.requirements["feature-a-1"].project, "Main")
            self.assertEqual(run_state.requirements["feature-a-1"].component("redis")["final"], 6485)
            self.assertEqual(run_state.services["feature-a-1 Backend"].pid, 33333)
            self.assertEqual(run_state.services["feature-a-1 Frontend"].pid, 22222)

    def test_restart_project_configured_missing_backend_starts_without_prior_service_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "echo backend",
                    "ENVCTL_FRONTEND_START_CMD": "echo frontend",
                    "ENVCTL_UI_SPINNER_MODE": "off",
                },
            )
            previous_requirements = RequirementsResult(
                project="Main",
                db={"requested": 5432, "final": 5432, "retries": 0, "success": True, "enabled": False},
                redis={"requested": 6379, "final": 6379, "retries": 0, "success": True, "enabled": False},
                n8n={"requested": 5678, "final": 5678, "retries": 0, "success": True, "enabled": False},
                supabase={"requested": 5432, "final": 5432, "retries": 0, "success": True, "enabled": False},
                health="healthy",
            )
            previous_state = RunState(
                run_id="run-old",
                mode="main",
                services={
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo / "frontend"),
                        requested_port=9000,
                        actual_port=9000,
                        pid=22222,
                        status="running",
                    ),
                },
                requirements={"Main": previous_requirements},
                metadata={
                    "project_roots": {"Main": str(repo)},
                    "dashboard_project_configured_services": {"Main": ["backend", "frontend"]},
                },
            )
            context = ProjectContext(
                name="Main",
                root=repo,
                ports={
                    "backend": PortPlan("Main", 8000, 8000, 8000, "requested"),
                    "frontend": PortPlan("Main", 9000, 9000, 9000, "requested"),
                    "db": PortPlan("Main", 5432, 5432, 5432, "requested"),
                    "redis": PortPlan("Main", 6379, 6379, 6379, "requested"),
                    "n8n": PortPlan("Main", 5678, 5678, 5678, "requested"),
                },
            )
            captured_state: dict[str, RunState] = {}

            engine._try_load_existing_state = lambda mode=None, strict_mode_match=False: previous_state  # type: ignore[method-assign]
            engine._discover_projects = lambda mode: [context]  # type: ignore[method-assign]
            engine._reserve_project_ports = lambda _context, route=None: None  # type: ignore[method-assign]

            def start_project_context(
                *,
                context: ProjectContext,
                mode: str,
                route: Any,
                run_id: str,
            ) -> ProjectStartupResult:
                _ = context, mode, run_id
                self.assertTrue(bool(route.flags.get("_restart_request")))
                self.assertEqual(route.flags.get("services"), ["Main Backend"])
                self.assertEqual(route.flags.get("restart_service_types"), ["backend"])
                return ProjectStartupResult(
                    requirements=previous_requirements,
                    services={
                        "Main Backend": ServiceRecord(
                            name="Main Backend",
                            type="backend",
                            cwd=str(repo / "backend"),
                            requested_port=8000,
                            actual_port=8000,
                            pid=33333,
                            status="running",
                        )
                    },
                    warnings=[],
                )

            engine._start_project_context = start_project_context  # type: ignore[method-assign]
            engine._write_artifacts = (
                lambda run_state, contexts, errors=None: captured_state.setdefault("state", run_state)
            )  # type: ignore[method-assign]

            route = parse_route(["--restart", "Main", "--batch"], env={"ENVCTL_DEFAULT_MODE": "main"})
            route.flags.update(
                {
                    "services": ["Main Backend"],
                    "restart_service_types": ["backend"],
                    "restart_include_requirements": False,
                }
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            run_state = captured_state["state"]
            self.assertEqual(run_state.services["Main Frontend"].pid, 22222)
            self.assertEqual(run_state.services["Main Backend"].pid, 33333)
            self.assertEqual(
                run_state.metadata.get("dashboard_project_configured_services"),
                {"Main": ["backend", "frontend"]},
            )
