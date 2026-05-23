from __future__ import annotations

import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.test_output.parser_base import strip_ansi

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
    _FakeProcessRunner,
    _TtyStringIO,
)


class EngineRuntimeEnvStartupTests(_EngineRuntimeRealStartupTestCase):
    def test_main_restart_real_startup_path_preserves_ports_and_frontend_vite_backend_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._backend_frontend_only_config(repo, runtime),
                env={"ENVCTL_UI_SPINNER_MODE": "off"},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.auto_track_listener_ports = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]

            with redirect_stdout(StringIO()):
                self.assertEqual(engine.dispatch(parse_route(["--main", "--batch"], env={})), 0)
            fake_runner.start_background_calls.clear()
            fake_runner.start_background_envs.clear()

            with redirect_stdout(StringIO()):
                code = engine.dispatch(self._restart_route())

            self.assertEqual(code, 0, [event for event in engine.events if event.get("event") == "startup.failed"])
            state = engine._try_load_existing_state(mode="main", strict_mode_match=True)
            self.assertIsNotNone(state)
            assert state is not None
            self.assertEqual(state.services["Main Backend"].actual_port, 8000)
            self.assertEqual(state.services["Main Frontend"].actual_port, 9000)
            frontend_envs = self._frontend_envs(fake_runner, repo / "frontend")
            self.assertTrue(frontend_envs)
            self.assertEqual(frontend_envs[-1].get("VITE_BACKEND_URL"), "http://localhost:8000")
            self.assertEqual(frontend_envs[-1].get("VITE_API_URL"), "http://localhost:8000/api/v1")
            runtime_map = build_runtime_map(state)
            self.assertEqual(runtime_map["projection"]["Main"]["backend_url"], "http://localhost:8000")
            self.assertEqual(runtime_map["projection"]["Main"]["frontend_url"], "http://localhost:9000")
            with redirect_stdout(StringIO()) as dashboard_stdout:
                engine._print_dashboard_snapshot(state)
            dashboard_text = strip_ansi(dashboard_stdout.getvalue())
            self.assertIn("http://localhost:8000", dashboard_text)
            self.assertIn("http://localhost:9000", dashboard_text)
            self.assertFalse(
                [
                    event
                    for event in engine.events
                    if event.get("event") == "port.rebound" and event.get("service") in {"backend", "frontend"}
                ]
            )

    def test_backend_long_running_task_can_skip_listener_wait_and_start_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime,
                    extra={
                        "MAIN_FRONTEND_ENABLE": "false",
                        "TREES_BACKEND_ENABLE": "false",
                        "TREES_FRONTEND_ENABLE": "false",
                        "MAIN_POSTGRES_ENABLE": "false",
                        "MAIN_REDIS_ENABLE": "false",
                        "MAIN_N8N_ENABLE": "false",
                        "TREES_POSTGRES_ENABLE": "false",
                        "TREES_REDIS_ENABLE": "false",
                        "TREES_N8N_ENABLE": "false",
                        "MAIN_BACKEND_EXPECT_LISTENER": "false",
                    },
                ),
                env={},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            engine.process_runner = fake_runner  # type: ignore[attr-defined]

            code = engine.dispatch(parse_route(["--main", "--batch"], env={}))

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="main")
            self.assertIsNotNone(state)
            assert state is not None
            backend = state.services.get("Main Backend")
            self.assertIsNotNone(backend)
            assert backend is not None
            self.assertFalse(backend.listener_expected)
            self.assertIsNone(backend.requested_port)
            self.assertIsNone(backend.actual_port)
            self.assertEqual(backend.status, "running")

    def test_listener_failure_surfaces_backend_log_root_cause(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = self._config(
                repo,
                runtime,
                extra={"ENVCTL_RUNTIME_TRUTH_MODE": "strict"},
            )
            engine = PythonEngineRuntime(config, env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = False
            fake_runner.start_log_line = "ModuleNotFoundError: No module named 'psycopg2'"
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            out = _TtyStringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("ModuleNotFoundError", out.getvalue())
            self.assertIn("psycopg2", out.getvalue())

    def test_main_stale_backend_redis_env_does_not_override_managed_runtime_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "backend"
            env_file = backend_dir / ".env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            (backend_dir / "requirements.txt").write_text("fastapi==0.115.0\n", encoding="utf-8")
            env_file.write_text("REDIS_URL=redis://localhost:6518/0\nCUSTOM_BACKEND_FLAG=enabled\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(
                    repo,
                    runtime,
                    extra={
                        "MAIN_FRONTEND_ENABLE": "false",
                        "MAIN_POSTGRES_ENABLE": "false",
                        "MAIN_REDIS_ENABLE": "true",
                        "REDIS_PORT": "6603",
                    },
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
            state = engine._try_load_existing_state(mode="main")
            self.assertIsNotNone(state)
            assert state is not None
            requirements = state.requirements.get("Main")
            self.assertIsNotNone(requirements)
            assert requirements is not None
            redis_component = requirements.component("redis")
            self.assertFalse(bool(redis_component.get("external")))
            self.assertEqual(redis_component.get("final"), 6603)
            self.assertNotEqual(redis_component.get("external_url"), "redis://localhost:6518/0")
            backend_start_envs = [
                env
                for (_cmd, cwd), env in zip(fake_runner.start_background_calls, fake_runner.start_background_envs)
                if Path(cwd).resolve() == backend_dir.resolve() and isinstance(env, dict)
            ]
            self.assertTrue(backend_start_envs)
            self.assertTrue(any(env.get("REDIS_URL") == "redis://localhost:6603/0" for env in backend_start_envs))
            content = env_file.read_text(encoding="utf-8")
            self.assertIn("REDIS_URL=redis://localhost:6518/0", content)
            self.assertNotIn("REDIS_URL=redis://localhost:6603/0", content)

    def test_frontend_env_override_file_is_loaded_for_service_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            frontend_dir = repo / "trees" / "feature-a" / "1" / "frontend"
            frontend_override = repo / "config" / "frontend.override.env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            frontend_override.parent.mkdir(parents=True, exist_ok=True)
            frontend_override.write_text("CUSTOM_FRONTEND_FLAG=enabled\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"FRONTEND_ENV_FILE_OVERRIDE": str(frontend_override)},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            frontend_start_envs = [env for env in fake_runner.start_background_envs if isinstance(env, dict)]
            self.assertTrue(frontend_start_envs)
            self.assertTrue(any(env.get("CUSTOM_FRONTEND_FLAG") == "enabled" for env in frontend_start_envs))

    def test_frontend_relative_env_override_file_is_loaded_for_service_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            backend_dir = repo / "trees" / "feature-a" / "1" / "backend"
            frontend_dir = repo / "trees" / "feature-a" / "1" / "frontend"
            frontend_override = repo / "config" / "frontend.override.env"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            backend_dir.mkdir(parents=True, exist_ok=True)
            frontend_dir.mkdir(parents=True, exist_ok=True)
            frontend_override.parent.mkdir(parents=True, exist_ok=True)
            frontend_override.write_text("CUSTOM_FRONTEND_FLAG=relative\n", encoding="utf-8")

            engine = PythonEngineRuntime(
                self._config(repo, runtime),
                env={"FRONTEND_ENV_FILE_OVERRIDE": "config/frontend.override.env"},
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            frontend_start_envs = [env for env in fake_runner.start_background_envs if isinstance(env, dict)]
            self.assertTrue(frontend_start_envs)
            self.assertTrue(any(env.get("CUSTOM_FRONTEND_FLAG") == "relative" for env in frontend_start_envs))

