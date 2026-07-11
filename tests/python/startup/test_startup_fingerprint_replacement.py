# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.startup.startup_spinner_integration_test_support import *


class StartupFingerprintReplacementTests(StartupSpinnerIntegrationTestCase):
    def test_start_fingerprint_mismatch_replaces_existing_project_services_before_new_ports_are_reserved(self) -> None:
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
                        requested_port=8001,
                        actual_port=8001,
                        pid=11111,
                        status="running",
                    ),
                    "Main Frontend": ServiceRecord(
                        name="Main Frontend",
                        type="frontend",
                        cwd=str(repo / "frontend"),
                        requested_port=9001,
                        actual_port=9001,
                        pid=22222,
                        status="running",
                    ),
                },
                requirements={},
                metadata={"startup_identity": {"fingerprint": "previous-external-dependency-mode"}},
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
            terminate_calls: list[tuple[set[str] | None, bool]] = []
            call_order: list[str] = []

            engine._try_load_existing_state = (  # type: ignore[method-assign]
                lambda mode=None, strict_mode_match=False, project_names=None: previous_state
            )
            engine._discover_projects = lambda mode: [context]  # type: ignore[method-assign]
            engine._terminate_services_from_state = (  # type: ignore[method-assign]
                lambda state, selected_services, aggressive, verify_ownership: (
                    call_order.append("terminate"),
                    terminate_calls.append((selected_services, verify_ownership)),
                )
            )
            engine._start_project_context = (  # type: ignore[method-assign]
                lambda context, mode, route, run_id: (
                    call_order.append("start"),
                    ProjectStartupResult(
                        requirements=RequirementsResult(project="Main"),
                        services={
                            "Main Backend": ServiceRecord(
                                name="Main Backend",
                                type="backend",
                                cwd=str(repo / "backend"),
                                requested_port=8000,
                                actual_port=8000,
                                pid=33333,
                                status="running",
                            ),
                            "Main Frontend": ServiceRecord(
                                name="Main Frontend",
                                type="frontend",
                                cwd=str(repo / "frontend"),
                                requested_port=9000,
                                actual_port=9000,
                                pid=44444,
                                status="running",
                            ),
                        },
                        warnings=[],
                    ),
                )[1]
            )

            code = engine.dispatch(parse_route(["--main", "--managed-deps", "--batch"], env={}))

            self.assertEqual(code, 0)
            self.assertEqual(terminate_calls, [({"Main Backend", "Main Frontend"}, True)])
            self.assertEqual(call_order, ["terminate", "start"])
