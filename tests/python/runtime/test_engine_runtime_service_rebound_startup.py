from __future__ import annotations

import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.runtime_map import build_runtime_map
from envctl_engine.test_output.parser_base import strip_ansi

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
    _FakeProcessRunner,
)


class EngineRuntimeServiceReboundStartupTests(_EngineRuntimeRealStartupTestCase):
    def test_main_restart_real_startup_path_rebounds_backend_and_updates_frontend_vite_backend_env(self) -> None:
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
            engine.port_planner.availability_checker = lambda port: port != 8000

            with redirect_stdout(StringIO()):
                code = engine.dispatch(self._restart_route())

            self.assertEqual(code, 0, [event for event in engine.events if event.get("event") == "startup.failed"])
            state = engine._try_load_existing_state(mode="main", strict_mode_match=True)
            self.assertIsNotNone(state)
            assert state is not None
            self.assertEqual(state.services["Main Backend"].actual_port, 8001)
            self.assertEqual(state.services["Main Frontend"].actual_port, 9000)
            frontend_envs = self._frontend_envs(fake_runner, repo / "frontend")
            self.assertTrue(frontend_envs)
            self.assertEqual(frontend_envs[-1].get("VITE_BACKEND_URL"), "http://localhost:8001")
            self.assertEqual(frontend_envs[-1].get("VITE_API_URL"), "http://localhost:8001/api/v1")
            runtime_map = build_runtime_map(state)
            self.assertEqual(runtime_map["projection"]["Main"]["backend_url"], "http://localhost:8001")
            self.assertEqual(runtime_map["projection"]["Main"]["frontend_url"], "http://localhost:9000")
            with redirect_stdout(StringIO()) as dashboard_stdout:
                engine._print_dashboard_snapshot(state)
            dashboard_text = strip_ansi(dashboard_stdout.getvalue())
            self.assertIn("http://localhost:8001", dashboard_text)
            self.assertIn("http://localhost:9000", dashboard_text)
            backend_rebounds = [
                event
                for event in engine.events
                if event.get("event") == "port.rebound" and event.get("service") == "backend"
            ]
            self.assertEqual(len(backend_rebounds), 1)
            self.assertEqual(backend_rebounds[0].get("restart_preferred_port"), 8000)
            self.assertEqual(backend_rebounds[0].get("port"), 8001)
            self.assertEqual(backend_rebounds[0].get("restart_conflict_detail"), "listener")

    def test_startup_emits_service_retry_events_for_backend_and_frontend_conflicts(self) -> None:
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
                    "ENVCTL_TEST_CONFLICT_BACKEND": "1",
                    "ENVCTL_TEST_CONFLICT_FRONTEND": "1",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            retry_events = [event for event in engine.events if event.get("event") == "service.retry"]
            self.assertTrue(retry_events)
            self.assertTrue(any(event.get("service") == "backend" for event in retry_events))
            self.assertTrue(any(event.get("service") == "frontend" for event in retry_events))
            for event in retry_events:
                self.assertIsInstance(event.get("failed_port"), int)
                self.assertIsInstance(event.get("retry_port"), int)
                self.assertIsInstance(event.get("attempt"), int)

    def test_frontend_rebound_delta_uses_pid_scoped_listener_truth(self) -> None:
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
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_TEST_FRONTEND_REBOUND_DELTA": "2",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            plans = self._planned_ports(engine, "feature-a-1")
            preferred_frontend = plans["frontend"].final
            fake_runner.wait_for_port_overrides[preferred_frontend + 2] = False
            fake_runner.wait_for_pid_port_overrides[preferred_frontend + 2] = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            runtime_map = (runtime / "python-engine" / "runtime_map.json").read_text(encoding="utf-8")
            self.assertIn(f'"frontend_port": {preferred_frontend + 2}', runtime_map)

    def test_frontend_rebound_delta_reserves_busy_launch_ports_before_start(self) -> None:
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
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_TEST_FRONTEND_REBOUND_DELTA": "200",
                },
            )
            fake_runner = _FakeProcessRunner()
            fake_runner.auto_track_listener_ports = True
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = False
            preferred_frontend = self._planned_ports(engine, "feature-a-1")["frontend"].final
            blocked_launch_ports = {
                preferred_frontend + 200,
                preferred_frontend + 201,
                preferred_frontend + 202,
                preferred_frontend + 203,
            }
            engine.port_planner.availability_checker = lambda port: port not in blocked_launch_ports
            fake_runner.fail_start_ports.update(blocked_launch_ports)
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            started_ports = {
                int(env["PORT"])
                for env in fake_runner.start_background_envs
                if isinstance(env, dict) and isinstance(env.get("PORT"), str)
            }
            self.assertTrue(blocked_launch_ports.isdisjoint(started_ports), started_ports)
            self.assertIn(preferred_frontend + 204, started_ports)
            runtime_map = (runtime / "python-engine" / "runtime_map.json").read_text(encoding="utf-8")
            self.assertIn(f'"frontend_port": {preferred_frontend + 204}', runtime_map)

    def test_frontend_actual_port_discovery_handles_auto_rebound_without_test_override(self) -> None:
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
            fake_runner.wait_for_pid_port_result = True
            plans = self._planned_ports(engine, "feature-a-1")
            preferred_frontend = plans["frontend"].final
            fake_runner.wait_for_pid_port_overrides[preferred_frontend] = False
            fake_runner.find_pid_listener_port_overrides[preferred_frontend] = preferred_frontend + 4
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            runtime_map = (runtime / "python-engine" / "runtime_map.json").read_text(encoding="utf-8")
            self.assertIn(f'"frontend_port": {preferred_frontend + 4}', runtime_map)
            self.assertTrue(any(call[1] == preferred_frontend for call in fake_runner.find_pid_listener_port_calls))

    def test_startup_fails_without_real_commands_even_when_synthetic_envs_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "strict",
                    "POSTGRES_MAIN_ENABLE": "false",
                    "REDIS_ENABLE": "false",
                    "N8N_ENABLE": "false",
                    "SUPABASE_MAIN_ENABLE": "false",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_SYNTHETIC_TEST_MODE": "true",
                    "ENVCTL_SYNTHETIC_TEST_CONTEXT": "true",
                },
            )
            route = parse_route(["start", "--main", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("missing_service_start_command", out.getvalue())

    def test_service_log_and_runner_flags_are_forwarded_to_service_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                [
                    "--plan",
                    "feature-a",
                    "--batch",
                    "--log-profile",
                    "debug",
                    "--log-level",
                    "info",
                    "--backend-log-level",
                    "warn",
                    "--frontend-log-profile",
                    "quiet",
                    "--frontend-test-runner",
                    "bun",
                ],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertGreaterEqual(len(fake_runner.start_background_envs), 2)
            backend_env = fake_runner.start_background_envs[0] or {}
            frontend_env = fake_runner.start_background_envs[1] or {}
            self.assertEqual(backend_env.get("LOG_PROFILE_OVERRIDE"), "debug")
            self.assertEqual(backend_env.get("LOG_LEVEL_OVERRIDE"), "info")
            self.assertEqual(backend_env.get("BACKEND_LOG_LEVEL_OVERRIDE"), "warn")
            self.assertEqual(frontend_env.get("FRONTEND_LOG_PROFILE_OVERRIDE"), "quiet")
            self.assertEqual(frontend_env.get("FRONTEND_TEST_RUNNER"), "bun")

    def test_startup_defaults_to_parallel_backend_frontend_attach(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]

            code = engine.dispatch(parse_route(["--batch"], env={"ENVCTL_DEFAULT_MODE": "main"}))

            self.assertEqual(code, 0)
            attach_events = [event for event in engine.events if event.get("event") == "service.attach.execution"]
            self.assertTrue(attach_events)
            self.assertEqual(attach_events[-1].get("mode"), "parallel")

    def test_service_sequential_flag_forces_sequential_backend_frontend_attach(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]

            code = engine.dispatch(
                parse_route(
                    ["--batch", "--service-sequential"],
                    env={"ENVCTL_DEFAULT_MODE": "main"},
                )
            )

            self.assertEqual(code, 0)
            attach_events = [event for event in engine.events if event.get("event") == "service.attach.execution"]
            self.assertTrue(attach_events)
            self.assertEqual(attach_events[-1].get("mode"), "sequential")

    def test_start_trees_env_false_forces_sequential_startup_execution_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"RUN_SH_OPT_PARALLEL_TREES": "false"})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                ["--trees", "--project", "feature-a-1", "--project", "feature-b-1", "--batch"],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "sequential")
            self.assertEqual(latest.get("workers"), 1)
