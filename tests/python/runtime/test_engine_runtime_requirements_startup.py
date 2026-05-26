from __future__ import annotations

import json
import sys
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any, cast

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import ProjectContext, PythonEngineRuntime
from envctl_engine.state.models import PortPlan

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
    _FakeProcessRunner,
    _FakeSetupWorktreeRunner,
)


class EngineRuntimeRequirementsStartupTests(_EngineRuntimeRealStartupTestCase):
    def test_startup_uses_process_runner_for_requirements_and_services(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertGreaterEqual(len(fake_runner.run_calls), 3)
            self.assertGreaterEqual(len(fake_runner.start_background_calls), 2)

    def test_startup_summarizes_docker_daemon_outage_for_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime,
                    extra={"MAIN_POSTGRES_ENABLE": "true"},
                    include_commands=False,
                ),
                env={},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.docker_connect_error = (
                "failed to connect to the docker API at "
                "unix:///Users/kfiramar/.docker/run/docker.sock; "
                "check if the path is correct and if the daemon is running: "
                "dial unix /Users/kfiramar/.docker/run/docker.sock: connect: no such file or directory"
            )
            engine.process_runner = fake_runner  # type: ignore[attr-defined]

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--main", "--batch"], env={}))

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("Startup failed: Docker is not running.", rendered)
            self.assertIn("Docker is required for Main dependencies:", rendered)
            self.assertNotIn("FailureClass.HARD_START_FAILURE", rendered)
            self.assertEqual(fake_runner.start_calls, [])
            readiness_report_path = runtime / "python-engine" / "runtime_readiness_report.json"
            self.assertTrue(readiness_report_path.is_file())
            readiness_report = json.loads(readiness_report_path.read_text(encoding="utf-8"))
            self.assertIn("passed", readiness_report)
            self.assertIn("summary", readiness_report)
            run_state = json.loads((runtime / "python-engine" / "run_state.json").read_text(encoding="utf-8"))
            pointers = run_state.get("pointers", {})
            self.assertIn("runtime_readiness_report", pointers)
            pointer_path = Path(str(pointers.get("runtime_readiness_report")))
            self.assertEqual(pointer_path.name, "runtime_readiness_report.json")
            self.assertEqual(pointer_path.parent.name, str(run_state.get("run_id", "")))
            self.assertTrue(pointer_path.is_file())

    def test_startup_auto_truth_does_not_use_port_reachability_fallback_when_listener_probe_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_RUNTIME_TRUTH_MODE": "auto",
                    }
                ),
                env={
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 1'",
                },
            )
            engine._listener_probe_supported = True  # type: ignore[attr-defined]
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_pid_port_result = False
            fake_runner.wait_for_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 1)

    def test_startup_auto_truth_uses_port_reachability_fallback_when_listener_probe_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_RUNTIME_TRUTH_MODE": "auto",
                    }
                ),
                env={
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 1'",
                },
            )
            engine._listener_probe_supported = False  # type: ignore[attr-defined]
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_pid_port_result = False
            fake_runner.wait_for_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)

    def test_backend_requirements_bootstrap_installs_project_venv_dependencies_without_running_migrations_by_default(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            (backend_dir / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "DB_USER": "svc_user",
                    "DB_PASSWORD": "svc_pass",
                    "DB_NAME": "svc_db",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})
            planned_db_port = self._planned_ports(engine, "feature-a-1")["db"].final

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            pip_install_calls = [
                call
                for call in fake_runner.run_calls
                if len(call[0]) >= 4
                and call[0][1:4] == ("-m", "pip", "install")
                and call[0][-2:] == ("-r", "requirements.txt")
            ]
            self.assertTrue(pip_install_calls)
            self.assertTrue(
                any(
                    len(call[0]) >= 3 and call[0][1:3] == ("-m", "venv") and str(call[0][-1]).endswith("/backend/venv")
                    for call in fake_runner.run_calls
                )
            )
            alembic_calls = [call for call in fake_runner.run_calls if call[0][-3:] == ("alembic", "upgrade", "head")]
            self.assertEqual(alembic_calls, [])
            bootstrap_envs = [env for env in fake_runner.run_envs if isinstance(env, dict)]
            self.assertTrue(
                any(
                    env.get("DATABASE_URL")
                    == f"postgresql+asyncpg://svc_user:svc_pass@localhost:{planned_db_port}/svc_db"
                    for env in bootstrap_envs
                )
            )
            self.assertTrue(any(env.get("DB_USER") == "svc_user" for env in bootstrap_envs))
            self.assertTrue(any(env.get("DB_PASSWORD") == "svc_pass" for env in bootstrap_envs))
            self.assertTrue(any(env.get("DB_NAME") == "svc_db" for env in bootstrap_envs))

    def test_main_backend_launch_env_templates_enable_dynamic_supabase_and_redis_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "backend"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (repo / ".envctl").write_text(
                "\n".join(
                    [
                        "# >>> envctl managed startup config >>>",
                        "ENVCTL_DEFAULT_MODE=main",
                        "MAIN_FRONTEND_ENABLE=false",
                        "DB_PORT=5544",
                        "REDIS_PORT=6399",
                        "ENVCTL_BACKEND_START_CMD=python -c 'import time; time.sleep(1)'",
                        "# <<< envctl managed startup config <<<",
                        "",
                        "# >>> envctl backend launch env >>>",
                        "DATABASE_URL=${ENVCTL_SOURCE_DATABASE_URL}",
                        "REDIS_URL=${ENVCTL_SOURCE_REDIS_URL}",
                        "N8N_URL=${ENVCTL_SOURCE_N8N_URL}",
                        "SUPABASE_URL=${ENVCTL_SOURCE_SUPABASE_URL}",
                        "# <<< envctl backend launch env <<<",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            python_bin = sys.executable
            engine = PythonEngineRuntime(
                load_config(
                    {
                        "RUN_REPO_ROOT": str(repo),
                        "RUN_SH_RUNTIME_DIR": str(runtime),
                        "ENVCTL_REQUIREMENT_POSTGRES_CMD": f'{python_bin} -c "import sys; sys.exit(0)"',
                        "ENVCTL_REQUIREMENT_REDIS_CMD": f'{python_bin} -c "import sys; sys.exit(0)"',
                        "ENVCTL_REQUIREMENT_N8N_CMD": f'{python_bin} -c "import sys; sys.exit(0)"',
                        "ENVCTL_REQUIREMENT_SUPABASE_CMD": f'{python_bin} -c "import sys; sys.exit(0)"',
                    }
                ),
                env={},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--main", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            requirement_events = [
                event
                for event in engine.events
                if event.get("event") == "requirements.start" and event.get("project") == "Main"
            ]
            self.assertCountEqual([event.get("service") for event in requirement_events], ["redis", "supabase"])
            backend_start_env = fake_runner.start_background_envs[-1]
            self.assertIsNotNone(backend_start_env)
            assert backend_start_env is not None
            self.assertEqual(
                backend_start_env.get("DATABASE_URL"),
                "postgresql+asyncpg://postgres:supabase-db-password@localhost:5544/postgres",
            )
            self.assertEqual(backend_start_env.get("REDIS_URL"), "redis://localhost:6399/0")
            self.assertNotIn("N8N_URL", backend_start_env)
            self.assertEqual(backend_start_env.get("SUPABASE_URL"), "http://localhost:54321")

    def test_startup_fails_when_requirements_are_unavailable_in_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc 'exit 1'",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertEqual(fake_runner.start_background_calls, [])

    def test_requirements_exit_zero_without_listener_fails_readiness_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc 'exit 0'",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = False
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("probe timeout", out.getvalue())
            self.assertEqual(fake_runner.start_background_calls, [])

    def test_requirement_listener_probe_timeout_honors_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc 'exit 0'",
                    "ENVCTL_REQUIREMENT_LISTENER_TIMEOUT_SECONDS": "25",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = False
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("probe timeout", out.getvalue())
            plans = self._planned_ports(engine, "feature-a-1")
            self.assertTrue(
                any(port == plans["db"].final and timeout == 25.0 for port, timeout in fake_runner.wait_for_port_calls),
                msg=fake_runner.wait_for_port_calls,
            )

    def test_startup_recovers_when_bind_conflicts_exceed_default_retry_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc true",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_BIND_MAX_RETRIES": "8",
                    "ENVCTL_TEST_CONFLICT_POSTGRES": "4",
                    "ENVCTL_TEST_CONFLICT_REDIS": "4",
                    "ENVCTL_TEST_CONFLICT_N8N": "4",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            requirements = state.requirements["feature-a-1"]
            self.assertGreaterEqual(int(requirements.component("postgres").get("retries", 0)), 4)
            self.assertGreaterEqual(int(requirements.component("redis").get("retries", 0)), 4)
            self.assertGreaterEqual(int(requirements.component("n8n").get("retries", 0)), 4)
            self.assertNotIn("Requirements unavailable", out.getvalue())

    def test_startup_emits_requirements_retry_events_for_bind_conflict_retries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_SUPABASE_CMD": "sh -lc true",
                    "ENVCTL_BACKEND_START_CMD": "sh -lc true",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc true",
                    "ENVCTL_TEST_CONFLICT_POSTGRES": "1",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            retry_events = [event for event in engine.events if event.get("event") == "requirements.retry"]
            self.assertTrue(retry_events)
            postgres_events = [event for event in retry_events if event.get("service") == "postgres"]
            self.assertTrue(postgres_events)
            latest = postgres_events[-1]
            self.assertEqual(latest.get("project"), "feature-a-1")
            self.assertEqual(latest.get("failure_class"), "bind_conflict_retryable")
            self.assertIsInstance(latest.get("failed_port"), int)
            self.assertIsInstance(latest.get("retry_port"), int)
            self.assertIsInstance(latest.get("attempt"), int)

    def test_main_requirement_toggles_are_respected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "true",
                    "REDIS_MAIN_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                    "N8N_ENABLE": "true",
                    "N8N_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            main_context = engine._discover_projects(mode="main")[0]

            requirements = engine._start_requirements_for_project(main_context, mode="main")

            self.assertFalse(requirements.component("postgres")["enabled"])
            self.assertFalse(requirements.component("redis")["enabled"])
            self.assertFalse(requirements.component("n8n")["enabled"])
            self.assertFalse(requirements.component("supabase")["enabled"])

    def test_main_services_local_flag_overrides_main_requirements_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = self._config(repo, runtime)
            engine = PythonEngineRuntime(config, env={})
            route = parse_route(["--main", "--main-services-local"], env={})

            self.assertFalse(engine._requirement_enabled("postgres", mode="main", route=route))
            self.assertTrue(engine._requirement_enabled("redis", mode="main", route=route))
            self.assertTrue(engine._requirement_enabled("n8n", mode="main", route=route))
            self.assertTrue(engine._requirement_enabled("supabase", mode="main", route=route))

    def test_conflicting_main_requirements_flags_fail_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(["--main-services-local", "--main-services-remote", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("Conflicting main requirements flags", out.getvalue())

    def test_command_resolution_fails_without_real_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "POSTGRES_TREES_ENABLE": "true",
                }
            )
            engine = PythonEngineRuntime(config, env={})

            with self.assertRaises(RuntimeError):
                engine._requirement_command(service_name="postgres", port=5432)
            with self.assertRaises(RuntimeError):
                engine._service_start_command(service_name="backend")
            with self.assertRaises(RuntimeError):
                engine._service_start_command(service_name="frontend")

    def test_requirements_non_strict_allows_missing_requirement_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                extra={"ENVCTL_REQUIREMENTS_STRICT": "false"},
                include_commands=False,
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            engine._command_exists = lambda executable: False

            plan = PortPlan(project="proj", requested=5432, assigned=5432, final=5432, source="test")
            context = ProjectContext(
                name="proj",
                root=repo,
                ports={"db": plan, "redis": plan, "n8n": plan, "supabase": plan, "backend": plan, "frontend": plan},
            )

            outcome = cast(Any, engine)._start_requirement_component(
                context,
                "postgres",
                plan,
                reserve_next=lambda port: port,
                route=None,
            )

            self.assertFalse(outcome.success)
            self.assertIn("missing_requirement_start_command", str(outcome.error))

    def test_startup_rejects_incomplete_worktree_before_launching_configured_uvicorn(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (tree_root / ".omx").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                extra={
                    "ENVCTL_BACKEND_START_CMD": "python -m uvicorn app.main:app --host 0.0.0.0 --port {port}",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                },
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            rendered = out.getvalue()
            self.assertEqual(code, 1)
            self.assertIn("No tree paths found for requested project filter(s): feature-a.", rendered)
            self.assertIn("No projects discovered for selected mode.", rendered)
            self.assertNotIn("missing_service_directory", rendered)
            self.assertNotIn("No module named uvicorn", rendered)
            self.assertEqual(fake_runner.start_background_calls, [])

    def test_requirements_use_native_adapters_before_command_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "TREES_POSTGRES_ENABLE": "true",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            engine._command_exists = lambda command: command == "docker"  # type: ignore[method-assign]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertNotIn("missing_requirement_start_command", out.getvalue())
            self.assertIn("missing_service_start_command", out.getvalue())
            self.assertTrue(any(call[0][:2] == ("docker", "ps") for call in fake_runner.run_calls))

    def test_start_fails_when_duplicate_project_identities_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a-1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("Duplicate project identities detected", out.getvalue())

    def test_entire_system_plan_noops_app_services_when_no_local_system_is_configured(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                }
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--entire-system", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            rendered = out.getvalue()
            self.assertEqual(code, 0)
            self.assertIn("no local app system is configured", rendered)
            self.assertIn("--entire-system was honored", rendered)
            self.assertNotIn("missing_requirement_start_command", out.getvalue())
            self.assertNotIn("missing_service_start_command", rendered)
            self.assertNotIn("local app startup failed", rendered)
            self.assertEqual(fake_runner.start_background_calls, [])

            skipped_events = [event for event in engine.events if event.get("event") == "service.attach.skipped"]
            self.assertTrue(skipped_events)
            self.assertEqual(skipped_events[-1].get("reason"), "no_system_configured")
            self.assertEqual(skipped_events[-1].get("requested_scope"), "entire-system")
            self.assertEqual(skipped_events[-1].get("selected_service_types"), ["backend", "frontend"])

    def test_explicit_tree_backend_enable_keeps_missing_command_failure_actionable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "TREES_BACKEND_ENABLE": "true",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--entire-system", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            rendered = out.getvalue()
            self.assertEqual(code, 1)
            self.assertIn("missing_service_start_command", rendered)
            self.assertNotIn("no local app system is configured", rendered)
            self.assertEqual(fake_runner.start_background_calls, [])

    def test_runtime_env_overrides_forward_docker_and_setup_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            route = parse_route(
                [
                    "--plan",
                    "feature-a",
                    "--docker",
                    "--setup-worktree-existing",
                    "--recreate-existing-worktree",
                    "--setup-include-worktrees",
                    "feature-a-1,feature-a-2",
                    "--seed-requirements-from-base",
                    "--stop-all-remove-volumes",
                ],
                env={},
            )

            env = engine._runtime_env_overrides(route)

            self.assertEqual(env.get("DOCKER_MODE"), "true")
            self.assertEqual(env.get("SETUP_WORKTREE_EXISTING"), "true")
            self.assertEqual(env.get("SETUP_WORKTREE_RECREATE"), "true")
            self.assertEqual(env.get("SETUP_INCLUDE_WORKTREES_RAW"), "feature-a-1,feature-a-2")
            self.assertEqual(env.get("SEED_REQUIREMENTS_FROM_BASE"), "true")
            self.assertEqual(env.get("RUN_SH_COMMAND_STOP_ALL_REMOVE_VOLUMES"), "true")

            route_no_seed = parse_route(
                [
                    "--plan",
                    "feature-a",
                    "--no-seed-requirements-from-base",
                ],
                env={},
            )
            env_no_seed = engine._runtime_env_overrides(route_no_seed)
            self.assertEqual(env_no_seed.get("SEED_REQUIREMENTS_FROM_BASE"), "false")
