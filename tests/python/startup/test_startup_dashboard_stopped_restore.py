# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.startup.startup_spinner_integration_test_support import *


class StartupDashboardStoppedRestoreTests(StartupSpinnerIntegrationTestCase):
    def test_startup_restores_dashboard_stopped_services_instead_of_auto_resuming_partial_state(self) -> None:
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
            captured_state: dict[str, RunState] = {}

            engine._try_load_existing_state = (  # type: ignore[method-assign]
                lambda mode=None, strict_mode_match=False, project_names=None: previous_state
            )
            engine._discover_projects = lambda mode: [context]  # type: ignore[method-assign]
            engine._reserve_project_ports = lambda _context, route=None: None  # type: ignore[method-assign]
            engine._resume = lambda route: self.fail("startup should start stopped services, not auto-resume")  # type: ignore[method-assign]

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

            code = engine.dispatch(parse_route(["--batch"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            run_state = captured_state["state"]
            self.assertEqual(run_state.services["Main Backend"].pid, 11111)
            self.assertEqual(run_state.services["Main Frontend"].pid, 44444)
            self.assertNotIn("dashboard_stopped_services", run_state.metadata)
