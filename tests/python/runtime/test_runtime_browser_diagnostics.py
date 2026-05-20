from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.config import DependencyEnvTemplateEntry, load_config
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.endpoints_command_support import build_endpoints_payload
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.startup.finalization import build_success_run_state
from envctl_engine.startup.session import StartupSession
from envctl_engine.state import dump_state
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord


class _HealthyRunner:
    def is_pid_running(self, _pid: int) -> bool:
        return True

    def wait_for_port(self, _port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
        _ = host, timeout
        return True

    def wait_for_pid_port(
        self,
        _pid: int,
        _port: int,
        *,
        host: str = "127.0.0.1",
        timeout: float = 30.0,
        debug_pid_wait_group: str = "",
    ) -> bool:
        _ = host, timeout, debug_pid_wait_group
        return True

    def pid_owns_port(self, _pid: int, _port: int) -> bool:
        return True


class RuntimeBrowserDiagnosticsTests(unittest.TestCase):
    def _runtime_with_state(self, state: RunState, *, env: dict[str, str] | None = None) -> PythonEngineRuntime:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        runtime_root = Path(tmpdir.name) / "runtime"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime_root),
                "ENVCTL_RUNTIME_TRUTH_MODE": "best_effort",
            }
        )
        runtime = PythonEngineRuntime(config, env=env or {})
        dump_state(state, str(runtime._run_state_path()))
        return runtime

    def test_health_json_exposes_redacted_browser_runtime_diagnostics_and_stale_port_warnings(self) -> None:
        state = RunState(
            run_id="run-browser",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/repo/backend",
                    project="Main",
                    status="running",
                    pid=101,
                    actual_port=8100,
                ),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend",
                    type="frontend",
                    cwd="/repo/frontend",
                    project="Main",
                    status="running",
                    pid=102,
                    actual_port=3100,
                ),
            },
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    supabase={
                        "enabled": True,
                        "success": True,
                        "runtime_status": "healthy",
                        "resources": {"db": 55432, "api": 55421, "primary": 55432},
                    },
                )
            },
            metadata={
                "runtime_launch_diagnostics": {
                    "Main": {
                        "frontend": {
                            "env": {
                                "VITE_API_URL": "http://localhost:9999/api/v1",
                                "VITE_SUPABASE_URL": "http://localhost:9998",
                                "VITE_SUPABASE_ANON_KEY": "anon-secret-value",
                                "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
                            },
                            "command_source": "configured",
                            "argv": ["npm", "run", "dev"],
                        },
                        "backend": {
                            "env": {
                                "FRONTEND_BASE_URL": "http://localhost:3100",
                                "CORS_ORIGINS_RAW": "http://localhost:3100,http://127.0.0.1:3100",
                                "SUPABASE_SERVICE_ROLE_KEY": "service-role-secret",
                            },
                            "cors": {
                                "projected": True,
                                "env_key": "CORS_ORIGINS_RAW",
                                "frontend_origin": "http://localhost:3100",
                                "origins": ["http://localhost:3100", "http://127.0.0.1:3100"],
                            },
                            "command_source": "configured",
                            "argv": ["uvicorn", "app:app"],
                        },
                    }
                }
            },
        )
        runtime = self._runtime_with_state(state)
        runtime.process_runner = _HealthyRunner()  # type: ignore[assignment]

        stdout = StringIO()
        with redirect_stdout(stdout):
            code = runtime.dispatch(parse_route(["health", "--main", "--json"], env={}))

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        diagnostics = payload["runtime_diagnostics"]["projects"]["Main"]
        self.assertEqual(diagnostics["backend"]["url"], "http://localhost:8100")
        self.assertEqual(diagnostics["frontend"]["url"], "http://localhost:3100")
        self.assertEqual(diagnostics["dependencies"]["supabase"]["api_url"], "http://localhost:55421")
        self.assertTrue(diagnostics["dependencies"]["supabase"]["anon_key_present"])
        self.assertEqual(diagnostics["frontend"]["env"]["VITE_API_URL"], "http://localhost:9999/api/v1")
        self.assertEqual(diagnostics["frontend"]["env"]["VITE_SUPABASE_ANON_KEY"], "<redacted>")
        self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", json.dumps(diagnostics))
        self.assertEqual(diagnostics["backend"]["cors"]["env_key"], "CORS_ORIGINS_RAW")
        warning_codes = [warning["code"] for warning in payload["warnings"]]
        self.assertIn("frontend_env_backend_port_mismatch", warning_codes)
        self.assertIn("frontend_env_supabase_port_mismatch", warning_codes)

    def test_explain_startup_json_includes_env_projection_preview_with_secret_redaction(self) -> None:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        (repo / ".git").mkdir(parents=True, exist_ok=True)
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(Path(tmpdir.name) / "runtime"),
                "MAIN_SUPABASE_ENABLE": "true",
                "SUPABASE_PUBLIC_PORT": "54321",
                "MAIN_FRONTEND_DEPENDENCY_ENV": "true",
                "ENVCTL_FRONTEND_ENV__VITE_SUPABASE_URL": "${ENVCTL_SOURCE_SUPABASE_URL}",
                "ENVCTL_FRONTEND_ENV__VITE_SUPABASE_ANON_KEY": "${ENVCTL_SOURCE_SUPABASE_ANON_KEY}",
                "ENVCTL_BACKEND_CORS_ENV_KEY": "CORS_ORIGINS_RAW",
            }
        )
        config.main_frontend_dependency_env_section_present = True
        config.main_frontend_dependency_env_templates = (
            DependencyEnvTemplateEntry("VITE_SUPABASE_URL", "${ENVCTL_SOURCE_SUPABASE_URL}", 1),
            DependencyEnvTemplateEntry("VITE_SUPABASE_ANON_KEY", "${ENVCTL_SOURCE_SUPABASE_ANON_KEY}", 2),
        )
        runtime = PythonEngineRuntime(config, env={})

        stdout = StringIO()
        with redirect_stdout(stdout):
            code = runtime.dispatch(parse_route(["explain-startup", "--json"], env={}))

        payload = json.loads(stdout.getvalue())
        self.assertEqual(code, 0)
        self.assertIn("env_projection", payload)
        project = payload["env_projection"]["projects"]["Main"]
        supabase_api_port = project["dependency_ports"]["supabase"]["api"]
        self.assertIsInstance(supabase_api_port, int)
        frontend = project["services"]["frontend"]
        self.assertEqual(frontend["env"]["VITE_SUPABASE_URL"], f"http://localhost:{supabase_api_port}")
        self.assertEqual(frontend["env"]["VITE_SUPABASE_ANON_KEY"], "<redacted>")
        self.assertIn("ENVCTL_SOURCE_SUPABASE_URL", frontend["env"])
        self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", json.dumps(frontend))
        backend = project["services"]["backend"]
        self.assertEqual(backend["cors"]["env_key"], "CORS_ORIGINS_RAW")
        self.assertIn("argv", backend)

    def test_endpoints_payload_preserves_stopped_service_metadata(self) -> None:
        state = RunState(
            run_id="run-stopped",
            mode="main",
            services={
                "Main Backend": ServiceRecord(
                    name="Main Backend",
                    type="backend",
                    cwd="/repo/backend",
                    project="Main",
                    status="running",
                    actual_port=8100,
                )
            },
            metadata={
                "dashboard_stopped_services": [
                    {
                        "name": "Main Frontend",
                        "project": "Main",
                        "type": "frontend",
                        "reason": "user_stop",
                        "stopped_at": 1710000000.0,
                    }
                ]
            },
        )

        payload = build_endpoints_payload(state, project="Main", env={}, config=SimpleNamespace(raw={}))

        self.assertEqual(payload["frontend"]["status"], "stopped")
        self.assertEqual(payload["frontend"]["reason"], "user_stop")
        self.assertEqual(payload["frontend"]["stopped_at"], 1710000000.0)

    def test_success_run_state_preserves_runtime_launch_diagnostics_for_public_health(self) -> None:
        route = parse_route(["--headless"], env={})
        route.flags["_runtime_launch_diagnostics"] = {
            "Main": {
                "frontend": {
                    "env": {"VITE_API_URL": "http://localhost:8100/api/v1"},
                    "argv": ["npm", "run", "dev"],
                    "command_source": "configured",
                }
            }
        }
        runtime = SimpleNamespace(
            config=SimpleNamespace(
                runtime_scope_id="scope",
                dependency_env_section_present=False,
                frontend_dependency_env_section_present=False,
                main_frontend_dependency_env_section_present=False,
                trees_frontend_dependency_env_section_present=False,
                service_dependency_env_section_present={},
                mode_service_dependency_env_section_present={},
            ),
            _run_dir_path=lambda run_id: Path("/tmp") / run_id,
        )
        session = StartupSession(
            requested_route=route,
            effective_route=route,
            requested_command="start",
            runtime_mode="main",
            run_id="run-diagnostics",
            selected_contexts=[],
        )

        state = build_success_run_state(runtime, session)

        self.assertEqual(
            state.metadata["runtime_launch_diagnostics"]["Main"]["frontend"]["env"]["VITE_API_URL"],
            "http://localhost:8100/api/v1",
        )


if __name__ == "__main__":
    unittest.main()
