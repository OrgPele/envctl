from __future__ import annotations

import json
import tempfile
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from envctl_engine.config import load_config
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.test_output.parser_base import strip_ansi

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
    _FakeProcessRunner,
    _FakeSetupWorktreeRunner,
)


class EngineRuntimeRealStartupTests(_EngineRuntimeRealStartupTestCase):
    def test_debug_session_materialized_when_debug_mode_off(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            self.assertIsNone(engine._debug_recorder)

            code = engine.dispatch(parse_route(["--help"], env={}))

            self.assertEqual(code, 0)
            self.assertIsNotNone(engine._debug_recorder)
            session_id = engine._current_session_id()
            self.assertIsInstance(session_id, str)
            assert isinstance(session_id, str)
            self.assertTrue(session_id.startswith("session-"))

    def test_trees_discovery_supports_nested_feature_iteration_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "2").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            contexts = engine._discover_projects(mode="trees")

            names = [ctx.name for ctx in contexts]
            roots = [ctx.root.resolve() for ctx in contexts]
            self.assertEqual(names, ["feature-a-1", "feature-a-2", "feature-b-1"])
            self.assertIn((repo / "trees" / "feature-a" / "1").resolve(), roots)
            self.assertIn((repo / "trees" / "feature-a" / "2").resolve(), roots)
            self.assertIn((repo / "trees" / "feature-b" / "1").resolve(), roots)

    def test_startup_emits_port_lock_reclaim_event_with_previous_owner_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            planned_backend_port = self._planned_ports(engine, "feature-a-1")["backend"].final
            lock_path = engine.port_planner.lock_dir / f"{planned_backend_port}.lock"
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            lock_path.write_text(
                json.dumps(
                    {
                        "owner": "old-worker",
                        "session": "old-session",
                        "pid": 999999,
                        "created_at": "2000-01-01T00:00:00+00:00",
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            reclaim_events = [event for event in engine.events if event.get("event") == "port.lock.reclaim"]
            self.assertTrue(reclaim_events)
            latest = reclaim_events[-1]
            self.assertEqual(latest.get("port"), planned_backend_port)
            self.assertEqual(latest.get("reclaimed_owner"), "old-worker")
            self.assertEqual(latest.get("reclaimed_session"), "old-session")
            self.assertEqual(latest.get("reclaimed_pid"), 999999)

    def test_port_event_handler_emits_events_with_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine._on_port_event("port.lock.acquire", {"port": 8000, "owner": "proj"})

            self.assertTrue(engine.events)
            last = engine.events[-1]
            self.assertEqual(last.get("event"), "port.lock.acquire")
            self.assertEqual(last.get("port"), 8000)
            self.assertEqual(last.get("owner"), "proj")

    def test_startup_fails_when_listener_cannot_be_verified(self) -> None:
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
            engine._command_exists = lambda _cmd: False  # type: ignore[method-assign]
            fake_runner = _FakeSetupWorktreeRunner()
            fake_runner.wait_for_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 1)
            run_state = json.loads((runtime / "python-engine" / "run_state.json").read_text(encoding="utf-8"))
            pointers = run_state.get("pointers", {})
            self.assertIn("runtime_readiness_report", pointers)
            pointer_path = Path(str(pointers.get("runtime_readiness_report")))
            self.assertEqual(pointer_path.name, "runtime_readiness_report.json")
            self.assertEqual(pointer_path.parent.name, str(run_state.get("run_id", "")))
            self.assertTrue(pointer_path.is_file())

    def test_startup_auto_truth_uses_port_reachability_fallback_when_process_tree_probe_unavailable(self) -> None:
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
            fake_runner.process_tree_probe_supported = False
            fake_runner.wait_for_pid_port_result = False
            fake_runner.wait_for_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)

    def test_startup_strict_truth_does_not_use_port_reachability_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "strict",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_REQUIREMENT_POSTGRES_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_REDIS_CMD": "sh -lc true",
                    "ENVCTL_REQUIREMENT_N8N_CMD": "sh -lc true",
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 1'",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_pid_port_result = False
            fake_runner.wait_for_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 1)

    def test_listener_failure_output_renders_clickable_log_path_but_event_detail_stays_raw(self) -> None:
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
            engine = PythonEngineRuntime(config, env={"ENVCTL_UI_HYPERLINK_MODE": "on"})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = False
            fake_runner.start_log_line = "ModuleNotFoundError: No module named 'psycopg2'"
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            captured_events: list[tuple[str, dict[str, object]]] = []
            original_emit = engine._emit

            def capture_emit(event: str, **payload: object) -> None:
                captured_events.append((event, payload))
                original_emit(event, **payload)

            engine._emit = capture_emit  # type: ignore[method-assign]
            route = parse_route(["--plan", "feature-a", "--isolated-deps", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("\x1b]8;;file://", rendered)
            visible = strip_ansi(rendered)
            self.assertIn("backend is missing a required executable or module", visible)
            self.assertIn("log_path:", visible)
            failure_events = [payload for event, payload in captured_events if event == "service.failure"]
            self.assertTrue(failure_events)
            self.assertEqual(failure_events[0]["failure_class"], "dependency_missing")
            detail = str(failure_events[0]["detail"])
            self.assertIn("log_path:", detail)
            self.assertNotIn("\x1b]8;;", detail)

    def test_startup_fails_when_service_loses_listener_immediately_after_start(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "strict",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 1'",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            plans = self._planned_ports(engine, "feature-a-1")
            fake_runner.wait_for_pid_port_sequences[plans["backend"].final] = [True, False]
            fake_runner.wait_for_pid_port_sequences[plans["frontend"].final] = [True, True]
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            rendered = out.getvalue()
            self.assertIn("backend became", rendered)
            self.assertIn("after startup", rendered)

    def test_startup_fails_when_service_truth_degrades_before_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "ENVCTL_RUNTIME_TRUTH_MODE": "strict",
                }
            )
            engine = PythonEngineRuntime(
                config,
                env={
                    "ENVCTL_BACKEND_START_CMD": "sh -lc 'sleep 1'",
                    "ENVCTL_FRONTEND_START_CMD": "sh -lc 'sleep 1'",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            plans = self._planned_ports(engine, "feature-a-1")
            fake_runner.wait_for_pid_port_sequences[plans["backend"].final] = [True, True, True]
            fake_runner.wait_for_pid_port_sequences[plans["frontend"].final] = [True, True, False]
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 1)
            self.assertIn("service truth degraded after startup", out.getvalue())

    def test_auto_runtime_truth_degrades_when_lsof_is_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)

            with patch("envctl_engine.runtime.engine_runtime.shutil.which", return_value=None):
                engine = PythonEngineRuntime(self._config(repo, runtime), env={})
                engine.port_planner.availability_checker = lambda _port: True
                fake_runner = _FakeProcessRunner()
                fake_runner.wait_for_port_result = True
                fake_runner.wait_for_pid_port_result = False
                engine.process_runner = fake_runner  # type: ignore[attr-defined]
                route = parse_route(["--plan", "feature-a", "--batch"], env={})

                code = engine.dispatch(route)

            self.assertEqual(code, 0)

    def test_service_listener_failure_detail_includes_log_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeProcessRunner()
            fake_runner.pid_running_result = False
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            log_path = Path(tmpdir) / "frontend.log"
            log_path.write_text('error: script "dev" exited with code 127\n', encoding="utf-8")

            detail = engine._service_listener_failure_detail(log_path=str(log_path), pid=4242)

            self.assertIsInstance(detail, str)
            assert isinstance(detail, str)
            self.assertIn("process 4242 exited", detail)
            self.assertIn(f"log_path: {log_path}", detail)
            self.assertIn('log: error: script "dev" exited with code 127', detail)

    def test_startup_allows_at_least_one_bind_retry_when_bind_retry_budget_is_zero(self) -> None:
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
                    "ENVCTL_REQUIREMENT_BIND_MAX_RETRIES": "0",
                    "ENVCTL_TEST_CONFLICT_POSTGRES": "1",
                },
            )
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            requirements = state.requirements["feature-a-1"]
            self.assertGreaterEqual(int(requirements.component("postgres").get("retries", 0)), 1)
            retry_events = [
                event
                for event in engine.events
                if event.get("event") == "requirements.retry" and event.get("service") == "postgres"
            ]
            self.assertTrue(retry_events, msg=engine.events)
            self.assertNotIn("Requirements unavailable", out.getvalue())

    def test_main_services_remote_flag_disables_supabase_and_n8n(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            config = load_config(
                {
                    "RUN_REPO_ROOT": str(repo),
                    "RUN_SH_RUNTIME_DIR": str(runtime),
                    "SUPABASE_MAIN_ENABLE": "true",
                    "N8N_MAIN_ENABLE": "true",
                }
            )
            engine = PythonEngineRuntime(config, env={})
            route = parse_route(["--main", "--main-services-remote"], env={})

            self.assertFalse(engine._requirement_enabled("supabase", mode="main", route=route))
            self.assertFalse(engine._requirement_enabled("n8n", mode="main", route=route))
            self.assertTrue(engine._requirement_enabled("postgres", mode="main", route=route))

    def test_startup_records_real_commands_without_synthetic_flags(self) -> None:
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
            route = parse_route(["--plan", "feature-a", "--batch"], env={})

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(route)

            self.assertEqual(code, 0)
            state = engine._try_load_existing_state(mode="trees")
            self.assertIsNotNone(state)
            assert state is not None
            backend = state.services["feature-a-1 Backend"]
            frontend = state.services["feature-a-1 Frontend"]
            self.assertNotEqual(backend.status, "simulated")
            self.assertNotEqual(frontend.status, "simulated")
            self.assertFalse(state.requirements["feature-a-1"].component("postgres").get("simulated"))
            self.assertFalse(state.requirements["feature-a-1"].component("redis").get("simulated"))
            self.assertFalse(state.requirements["feature-a-1"].component("n8n").get("simulated"))
            self.assertNotIn("synthetic placeholder defaults", out.getvalue())

    def test_parallel_trees_flag_uses_parallel_startup_execution_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                ["--plan", "feature-a,feature-b", "--parallel-trees", "--parallel-trees-max", "2", "--batch"], env={}
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "parallel")
            self.assertEqual(latest.get("workers"), 2)

    def test_no_parallel_trees_flag_forces_sequential_startup_execution_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-b" / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={"RUN_SH_OPT_PARALLEL_TREES": "true"})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(["--plan", "feature-a,feature-b", "--no-parallel-trees", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "sequential")
            self.assertEqual(latest.get("workers"), 1)

    def test_start_prints_loading_progress_per_project(self) -> None:
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
            engine.env["ENVCTL_UI_SPINNER_MODE"] = "off"

            out = StringIO()
            with redirect_stdout(out):
                code = engine.dispatch(parse_route(["--plan", "feature-a", "--batch"], env={}))

            self.assertEqual(code, 0)
            output = out.getvalue()
            self.assertIn("Starting project feature-a-1", output)
            self.assertIn("Services ready for feature-a-1", output)
