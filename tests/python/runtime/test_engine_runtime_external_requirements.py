from __future__ import annotations

import socket
import tempfile
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.requirements.orchestrator import RequirementOutcome
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
    _healthy_http_server,
    _tcp_listener,
)


class EngineRuntimeExternalRequirementsTests(_EngineRuntimeRealStartupTestCase):
    def test_external_supabase_requirement_skips_managed_start_and_records_external_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, _healthy_http_server() as supabase_url:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                {
                    "MAIN_POSTGRES_ENABLE": "false",
                    "MAIN_REDIS_ENABLE": "false",
                    "MAIN_N8N_ENABLE": "false",
                    "MAIN_SUPABASE_ENABLE": "false",
                    "ENVCTL_REQUIREMENTS_STRICT": "true",
                },
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_DEPENDENCY_SUPABASE_MODE": "external",
                    "SUPABASE_URL": supabase_url,
                    "SUPABASE_ANON_KEY": "external-anon",
                },
            )
            context = engine._discover_projects(mode="main")[0]

            def fail_if_managed_start(*_args, **_kwargs):  # noqa: ANN001
                self.fail("external supabase must not invoke the managed requirement starter")

            engine._start_requirement_component = fail_if_managed_start  # type: ignore[method-assign]

            requirements = engine._start_requirements_for_project(context, mode="main")

            supabase = requirements.component("supabase")
            self.assertTrue(supabase["enabled"])
            self.assertTrue(supabase["success"])
            self.assertTrue(supabase["external"])
            self.assertEqual(supabase["runtime_status"], "healthy")
            self.assertEqual(supabase["external_url"], supabase_url)
            self.assertEqual(requirements.health, "healthy")

    def test_main_supabase_env_auto_uses_external_requirement_without_global_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, _healthy_http_server() as supabase_url:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                {
                    "MAIN_POSTGRES_ENABLE": "false",
                    "MAIN_REDIS_ENABLE": "false",
                    "MAIN_N8N_ENABLE": "false",
                    "MAIN_SUPABASE_ENABLE": "false",
                },
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "SUPABASE_URL": supabase_url,
                    "SUPABASE_ANON_KEY": "external-anon",
                },
            )
            context = engine._discover_projects(mode="main")[0]

            def fail_if_managed_start(*_args, **_kwargs):  # noqa: ANN001
                self.fail("main mode with complete external supabase env must not invoke managed startup")

            engine._start_requirement_component = fail_if_managed_start  # type: ignore[method-assign]

            requirements = engine._start_requirements_for_project(context, mode="main")

            supabase = requirements.component("supabase")
            self.assertTrue(supabase["enabled"])
            self.assertTrue(supabase["success"])
            self.assertTrue(supabase["external"])
            self.assertEqual(supabase["runtime_status"], "healthy")

    def test_main_supabase_backend_dotenv_auto_uses_external_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, _healthy_http_server() as supabase_url:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend = repo / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend.mkdir(parents=True, exist_ok=True)
            backend.joinpath(".env").write_text(
                f"SUPABASE_URL={supabase_url}\nSUPABASE_ANON_KEY=external-anon\n",
                encoding="utf-8",
            )

            config = self._config(
                repo,
                runtime,
                {
                    "MAIN_POSTGRES_ENABLE": "false",
                    "MAIN_REDIS_ENABLE": "false",
                    "MAIN_N8N_ENABLE": "false",
                    "MAIN_SUPABASE_ENABLE": "false",
                },
            )
            engine = PythonEngineRuntime(config, env={})
            context = engine._discover_projects(mode="main")[0]

            def fail_if_managed_start(*_args, **_kwargs):  # noqa: ANN001
                self.fail("main mode with complete backend .env Supabase values must not invoke managed startup")

            engine._start_requirement_component = fail_if_managed_start  # type: ignore[method-assign]

            requirements = engine._start_requirements_for_project(context, mode="main")

            supabase = requirements.component("supabase")
            self.assertTrue(supabase["enabled"])
            self.assertTrue(supabase["success"])
            self.assertTrue(supabase["external"])
            self.assertEqual(supabase["runtime_status"], "healthy")

    def test_main_root_dotenv_auto_uses_external_requirements_with_vite_supabase_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, _healthy_http_server() as supabase_url, _tcp_listener() as db_port:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            repo.joinpath(".env").write_text(
                f"SUPABASE_URL={supabase_url}\n"
                "VITE_SUPABASE_ANON_KEY=external-anon\n"
                f"DATABASE_URL=postgresql+asyncpg://app:secret@127.0.0.1:{db_port}/app\n",
                encoding="utf-8",
            )

            config = self._config(
                repo,
                runtime,
                {
                    "MAIN_POSTGRES_ENABLE": "false",
                    "MAIN_REDIS_ENABLE": "false",
                    "MAIN_N8N_ENABLE": "false",
                    "MAIN_SUPABASE_ENABLE": "false",
                },
            )
            engine = PythonEngineRuntime(config, env={})
            context = engine._discover_projects(mode="main")[0]

            def fail_if_managed_start(*_args, **_kwargs):  # noqa: ANN001
                self.fail("main mode with complete root .env values must not invoke managed startup")

            engine._start_requirement_component = fail_if_managed_start  # type: ignore[method-assign]

            requirements = engine._start_requirements_for_project(context, mode="main")

            supabase = requirements.component("supabase")
            postgres = requirements.component("postgres")
            self.assertTrue(supabase["enabled"])
            self.assertTrue(supabase["success"])
            self.assertTrue(supabase["external"])
            self.assertEqual(supabase["runtime_status"], "healthy")
            self.assertTrue(postgres["enabled"])
            self.assertTrue(postgres["success"])
            self.assertTrue(postgres["external"])
            self.assertEqual(postgres["runtime_status"], "healthy")

    def test_trees_supabase_env_defaults_to_managed_requirement_without_external_toggle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                {
                    "TREES_POSTGRES_ENABLE": "false",
                    "TREES_REDIS_ENABLE": "false",
                    "TREES_N8N_ENABLE": "false",
                    "TREES_SUPABASE_ENABLE": "true",
                },
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "SUPABASE_URL": "https://supabase.example.test",
                    "SUPABASE_ANON_KEY": "external-anon",
                },
            )
            context = SimpleNamespace(
                name="feature-a-1",
                root=repo / "trees" / "feature-a" / "1",
                ports=engine.port_planner.plan_project_stack("feature-a-1", index=0),
            )
            context.root.mkdir(parents=True, exist_ok=True)
            managed_starts: list[str] = []

            def fake_managed_start(context, component, plan, reserve_next, **_kwargs):  # noqa: ANN001
                managed_starts.append(component)
                return RequirementOutcome(
                    service_name=component,
                    success=True,
                    requested_port=plan.requested,
                    final_port=reserve_next(plan.final),
                    retries=0,
                )

            engine._start_requirement_component = fake_managed_start  # type: ignore[method-assign]

            route = parse_route(["--tree", "--isolated-deps"], env={})
            requirements = engine._start_requirements_for_project(context, mode="trees", route=route)

            supabase = requirements.component("supabase")
            self.assertEqual(managed_starts, ["supabase"])
            self.assertTrue(supabase["enabled"])
            self.assertTrue(supabase["success"])
            self.assertFalse(bool(supabase.get("external")))
            self.assertNotEqual(supabase.get("runtime_status"), "external")

    def test_external_redis_requirement_skips_managed_start_and_records_external_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir, _tcp_listener() as redis_port:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                {
                    "MAIN_POSTGRES_ENABLE": "false",
                    "MAIN_REDIS_ENABLE": "false",
                    "MAIN_N8N_ENABLE": "false",
                    "MAIN_SUPABASE_ENABLE": "false",
                },
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_EXTERNAL_DEPENDENCIES": "redis",
                    "REDIS_URL": f"redis://127.0.0.1:{redis_port}/0",
                },
            )
            context = engine._discover_projects(mode="main")[0]

            def fail_if_managed_start(*_args, **_kwargs):  # noqa: ANN001
                self.fail("external redis must not invoke the managed requirement starter")

            engine._start_requirement_component = fail_if_managed_start  # type: ignore[method-assign]

            requirements = engine._start_requirements_for_project(context, mode="main")

            redis = requirements.component("redis")
            self.assertTrue(redis["enabled"])
            self.assertTrue(redis["success"])
            self.assertTrue(redis["external"])
            self.assertEqual(redis["runtime_status"], "healthy")
            self.assertEqual(redis["resources"]["primary"], redis_port)
            self.assertEqual(redis["external_url"], f"redis://127.0.0.1:{redis_port}/0")

    def test_external_redis_requirement_fails_when_probe_cannot_connect(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(("127.0.0.1", 0))
            except PermissionError as exc:
                sock.close()
                self.skipTest(f"local TCP listener unavailable: {exc}")
            closed_port = int(sock.getsockname()[1])
            sock.close()

            config = self._config(
                repo,
                runtime,
                {
                    "MAIN_POSTGRES_ENABLE": "false",
                    "MAIN_REDIS_ENABLE": "false",
                    "MAIN_N8N_ENABLE": "false",
                    "MAIN_SUPABASE_ENABLE": "false",
                },
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_EXTERNAL_DEPENDENCIES": "redis",
                    "ENVCTL_EXTERNAL_DEPENDENCY_PROBE_TIMEOUT": "0.1",
                    "REDIS_URL": f"redis://127.0.0.1:{closed_port}/0",
                },
            )
            context = engine._discover_projects(mode="main")[0]

            requirements = engine._start_requirements_for_project(context, mode="main")

            redis = requirements.component("redis")
            self.assertTrue(redis["enabled"])
            self.assertFalse(redis["success"])
            self.assertTrue(redis["external"])
            self.assertEqual(redis["runtime_status"], "unreachable")
            self.assertIn("external probe failed", str(redis["error"]))
            self.assertEqual(requirements.health, "degraded")

    def test_main_auto_external_redis_probe_failure_records_unreachable_external_without_managed_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                sock.bind(("127.0.0.1", 0))
            except PermissionError as exc:
                sock.close()
                self.skipTest(f"local TCP listener unavailable: {exc}")
            closed_port = int(sock.getsockname()[1])
            sock.close()

            config = self._config(
                repo,
                runtime,
                {
                    "MAIN_POSTGRES_ENABLE": "false",
                    "MAIN_REDIS_ENABLE": "false",
                    "MAIN_N8N_ENABLE": "false",
                    "MAIN_SUPABASE_ENABLE": "false",
                },
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_EXTERNAL_DEPENDENCY_PROBE_TIMEOUT": "0.1",
                    "REDIS_URL": f"redis://127.0.0.1:{closed_port}/0",
                },
            )
            context = engine._discover_projects(mode="main")[0]

            def fail_if_managed_start(*_args, **_kwargs):  # noqa: ANN001
                self.fail("auto external redis must not invoke the managed requirement starter")

            engine._start_requirement_component = fail_if_managed_start  # type: ignore[method-assign]

            requirements = engine._start_requirements_for_project(context, mode="main")

            redis = requirements.component("redis")
            self.assertTrue(redis["enabled"])
            self.assertFalse(redis["success"])
            self.assertTrue(redis["external"])
            self.assertEqual(redis["runtime_status"], "unreachable")
            self.assertIn("external probe failed", str(redis["error"]))
            self.assertEqual(requirements.health, "degraded")

    def test_external_supabase_requirement_reports_missing_required_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                {
                    "MAIN_POSTGRES_ENABLE": "false",
                    "MAIN_REDIS_ENABLE": "false",
                    "MAIN_N8N_ENABLE": "false",
                    "MAIN_SUPABASE_ENABLE": "false",
                },
            )
            engine = PythonEngineRuntime(config, env={"ENVCTL_DEPENDENCY_SUPABASE_MODE": "external"})
            context = engine._discover_projects(mode="main")[0]

            requirements = engine._start_requirements_for_project(context, mode="main")

            supabase = requirements.component("supabase")
            self.assertTrue(supabase["enabled"])
            self.assertFalse(supabase["success"])
            self.assertTrue(supabase["external"])
            self.assertEqual(supabase["runtime_status"], "unreachable")
            self.assertIn("SUPABASE_URL", str(supabase["error"]))
            self.assertIn("SUPABASE_ANON_KEY", str(supabase["error"]))
            self.assertEqual(requirements.health, "degraded")
