from __future__ import annotations

import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.state import dump_state


class _FakeTruthRunner:
    def __init__(self, *, pid_running: bool, listener_up: bool) -> None:
        self.pid_running = pid_running
        self.listener_up = listener_up
        self.detected_listener_port: int | None = None
        self.wait_for_port_overrides: dict[int, bool] = {}
        self.listener_pid_map: dict[int, list[int]] = {}

    def is_pid_running(self, _pid: int) -> bool:
        return self.pid_running

    def wait_for_port(self, _port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
        _ = host, timeout
        return self.wait_for_port_overrides.get(_port, self.listener_up)

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
        return self.listener_up

    def pid_owns_port(self, _pid: int, _port: int) -> bool:
        return False
        _ = host, timeout
        return self.wait_for_port_overrides.get(_port, self.listener_up)

    def run(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs
        raise AssertionError("run() should not be called in health truth tests")

    def start(self, *args, **kwargs):  # noqa: ANN002, ANN003
        _ = args, kwargs
        raise AssertionError("start() should not be called in health truth tests")

    def find_pid_listener_port(
        self,
        _pid: int,
        _preferred_port: int,
        *,
        max_delta: int = 200,
    ) -> int | None:
        _ = max_delta
        return self.detected_listener_port

    def listener_pids_for_port(self, port: int) -> list[int]:
        return list(self.listener_pid_map.get(port, []))


class _FakeOwnershipRunner(_FakeTruthRunner):
    def __init__(self, *, pid_running: bool, listener_up: bool) -> None:
        super().__init__(pid_running=pid_running, listener_up=listener_up)
        self.listener_pid_map: dict[int, list[int]] = {}

    def pid_owns_port(self, _pid: int, _port: int) -> bool:
        return False

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
        return self.listener_up

    def process_tree_listener_pids(self, _pid: int, *, port: int | None = None) -> list[int]:
        if isinstance(port, int):
            return list(self.listener_pid_map.get(port, []))
        return []


class RuntimeHealthTruthTests(unittest.TestCase):
    def _make_runtime_with_services(
        self,
        *,
        services: dict[str, ServiceRecord],
        requirements: dict[str, RequirementsResult] | None = None,
        runtime_truth_mode: str = "strict",
        process_runner: object | None = None,
    ) -> PythonEngineRuntime:
        tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(tmpdir.cleanup)
        repo = Path(tmpdir.name) / "repo"
        runtime = Path(tmpdir.name) / "runtime"
        (repo / ".git").mkdir(parents=True, exist_ok=True)

        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
                "ENVCTL_RUNTIME_TRUTH_MODE": runtime_truth_mode,
            }
        )
        engine = PythonEngineRuntime(config, env={})
        state = RunState(
            run_id="run-1",
            mode="main",
            services=services,
            requirements=requirements or {},
        )
        dump_state(state, str(engine._run_state_path()))
        if process_runner is not None:
            engine.process_runner = process_runner  # type: ignore[assignment]
        return engine

    def _make_runtime_with_state(
        self,
        *,
        pid_running: bool,
        listener_up: bool,
        runtime_truth_mode: str = "strict",
    ) -> PythonEngineRuntime:
        service = ServiceRecord(
            name="Main Backend",
            type="backend",
            cwd="/tmp/backend",
            pid=12345,
            requested_port=8000,
            actual_port=8000,
            status="running",
        )
        return self._make_runtime_with_services(
            services={"Main Backend": service},
            runtime_truth_mode=runtime_truth_mode,
            process_runner=_FakeTruthRunner(pid_running=pid_running, listener_up=listener_up),
        )

    def test_health_returns_failure_when_pid_is_stale(self) -> None:
        engine = self._make_runtime_with_state(pid_running=False, listener_up=False)
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--health"], env={}))

        self.assertEqual(code, 1)
        self.assertIn("status=stale", out.getvalue())
        reconcile_events = [event for event in engine.events if event.get("event") == "state.reconcile"]
        self.assertTrue(reconcile_events)
        latest = reconcile_events[-1]
        self.assertEqual(latest.get("source"), "state_action.health")
        self.assertEqual(latest.get("missing_count"), 1)
        self.assertIn("Main Backend", latest.get("missing_services", []))

    def test_auto_truth_rebinds_stale_pid_when_listener_port_is_live(self) -> None:
        service = ServiceRecord(
            name="Main Frontend",
            type="frontend",
            cwd="/tmp/frontend",
            pid=2222,
            requested_port=9000,
            actual_port=9000,
            status="running",
        )
        runner = _FakeOwnershipRunner(pid_running=False, listener_up=False)
        runner.wait_for_port_overrides[9000] = True
        runner.listener_pid_map[9000] = [3333]
        engine = self._make_runtime_with_services(
            services={"Main Frontend": service},
            runtime_truth_mode="auto",
            process_runner=runner,
        )
        engine._listener_probe_supported = True  # type: ignore[attr-defined]

        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--health"], env={}))

        self.assertEqual(code, 0)
        self.assertIn("status=running", out.getvalue())

    def test_strict_truth_does_not_rebind_stale_pid_even_when_listener_port_is_live(self) -> None:
        service = ServiceRecord(
            name="Main Frontend",
            type="frontend",
            cwd="/tmp/frontend",
            pid=2222,
            requested_port=9000,
            actual_port=9000,
            status="running",
        )
        runner = _FakeOwnershipRunner(pid_running=False, listener_up=False)
        runner.wait_for_port_overrides[9000] = True
        runner.listener_pid_map[9000] = [3333]
        engine = self._make_runtime_with_services(
            services={"Main Frontend": service},
            runtime_truth_mode="strict",
            process_runner=runner,
        )

        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--health"], env={}))

        self.assertEqual(code, 1)
        self.assertIn("status=stale", out.getvalue())

    def test_health_returns_failure_when_listener_is_down(self) -> None:
        engine = self._make_runtime_with_state(pid_running=True, listener_up=False)
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--health"], env={}))

        self.assertEqual(code, 1)
        self.assertIn("status=unreachable", out.getvalue())

    def test_errors_reports_live_failures_from_runtime_truth(self) -> None:
        engine = self._make_runtime_with_state(pid_running=True, listener_up=False)
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--errors"], env={}))

        self.assertEqual(code, 1)
        self.assertIn("Main Backend", out.getvalue())



    def test_dashboard_snapshot_hides_urls_after_truth_reconcile(self) -> None:
        engine = self._make_runtime_with_state(pid_running=False, listener_up=False)
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--dashboard"], env={}))

        self.assertEqual(code, 0)
        rendered = out.getvalue()
        self.assertIn("Backend: n/a", rendered)
        self.assertNotIn("http://localhost:8000", rendered)
        reconcile_events = [event for event in engine.events if event.get("event") == "state.reconcile"]
        self.assertTrue(reconcile_events)
        self.assertEqual(reconcile_events[-1].get("source"), "dashboard.snapshot")

    def test_health_uses_wait_for_pid_port_when_available(self) -> None:
        engine = self._make_runtime_with_state(pid_running=True, listener_up=True)
        engine.process_runner = _FakeOwnershipRunner(pid_running=True, listener_up=True)  # type: ignore[assignment]

        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--health"], env={}))

        self.assertEqual(code, 0)
        self.assertIn("status=running", out.getvalue())

    def test_dashboard_preserves_frontend_url_when_listener_is_process_tree_owned(self) -> None:
        services = {
            "Main Backend": ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd="/tmp/backend",
                pid=1111,
                requested_port=8000,
                actual_port=8000,
                status="running",
            ),
            "Main Frontend": ServiceRecord(
                name="Main Frontend",
                type="frontend",
                cwd="/tmp/frontend",
                pid=2222,
                requested_port=9000,
                actual_port=9000,
                status="running",
            ),
        }
        engine = self._make_runtime_with_services(
            services=services,
            process_runner=_FakeOwnershipRunner(pid_running=True, listener_up=True),
        )
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--dashboard"], env={}))

        self.assertEqual(code, 0)
        rendered = out.getvalue()
        self.assertIn("Frontend: http://localhost:9000", rendered)
        self.assertNotIn("Frontend: n/a", rendered)

    def test_dashboard_shows_frontend_url_for_unreachable_service_with_known_port(self) -> None:
        services = {
            "Main Frontend": ServiceRecord(
                name="Main Frontend",
                type="frontend",
                cwd="/tmp/frontend",
                pid=2222,
                requested_port=9000,
                actual_port=9000,
                status="running",
            ),
        }
        engine = self._make_runtime_with_services(
            services=services,
            runtime_truth_mode="strict",
            process_runner=_FakeOwnershipRunner(pid_running=True, listener_up=False),
        )
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--dashboard"], env={}))

        self.assertEqual(code, 0)
        rendered = out.getvalue()
        self.assertIn("Frontend: http://localhost:9000", rendered)
        self.assertIn("[Unreachable]", rendered)
        self.assertNotIn("Frontend: n/a", rendered)

    def test_dashboard_shows_backend_url_for_unreachable_service_with_known_port(self) -> None:
        services = {
            "Main Backend": ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd="/tmp/backend",
                pid=1111,
                requested_port=8000,
                actual_port=8000,
                status="running",
            ),
        }
        engine = self._make_runtime_with_services(
            services=services,
            runtime_truth_mode="strict",
            process_runner=_FakeOwnershipRunner(pid_running=True, listener_up=False),
        )
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--dashboard"], env={}))

        self.assertEqual(code, 0)
        rendered = out.getvalue()
        self.assertIn("Backend: http://localhost:8000", rendered)
        self.assertIn("[Unreachable]", rendered)
        self.assertNotIn("Backend: n/a", rendered)

    def test_dashboard_shows_frontend_url_for_unknown_service_with_known_port(self) -> None:
        services = {
            "Main Frontend": ServiceRecord(
                name="Main Frontend",
                type="frontend",
                cwd="/tmp/frontend",
                pid=2222,
                requested_port=9000,
                actual_port=9000,
                status="unknown",
            ),
        }
        engine = self._make_runtime_with_services(
            services=services,
            runtime_truth_mode="best_effort",
            process_runner=_FakeOwnershipRunner(pid_running=True, listener_up=False),
        )
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--dashboard"], env={}))

        self.assertEqual(code, 0)
        rendered = out.getvalue()
        self.assertIn("Frontend: http://localhost:9000", rendered)
        self.assertNotIn("Frontend: n/a", rendered)
        self.assertIn("[Running]", rendered)

    def test_health_uses_port_reachability_fallback_in_auto_truth_mode(self) -> None:
        service = ServiceRecord(
            name="Main Frontend",
            type="frontend",
            cwd="/tmp/frontend",
            pid=2222,
            requested_port=9000,
            actual_port=9000,
            status="running",
        )
        runner = _FakeOwnershipRunner(pid_running=True, listener_up=False)
        runner.wait_for_port_overrides[9000] = True
        engine = self._make_runtime_with_services(
            services={"Main Frontend": service},
            runtime_truth_mode="auto",
            process_runner=runner,
        )
        engine._listener_probe_supported = True  # type: ignore[attr-defined]
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--health"], env={}))

        self.assertEqual(code, 0)
        self.assertIn("status=running", out.getvalue())

    def test_health_strict_mode_does_not_use_port_reachability_fallback(self) -> None:
        service = ServiceRecord(
            name="Main Frontend",
            type="frontend",
            cwd="/tmp/frontend",
            pid=2222,
            requested_port=9000,
            actual_port=9000,
            status="running",
        )
        runner = _FakeOwnershipRunner(pid_running=True, listener_up=False)
        runner.wait_for_port_overrides[9000] = True
        engine = self._make_runtime_with_services(
            services={"Main Frontend": service},
            runtime_truth_mode="strict",
            process_runner=runner,
        )
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--health"], env={}))

        self.assertEqual(code, 1)
        self.assertIn("status=unreachable", out.getvalue())

    def test_dashboard_recovers_frontend_url_when_actual_listener_port_is_discovered(self) -> None:
        services = {
            "Main Frontend": ServiceRecord(
                name="Main Frontend",
                type="frontend",
                cwd="/tmp/frontend",
                pid=3333,
                requested_port=9000,
                actual_port=9000,
                status="running",
            ),
        }
        runner = _FakeOwnershipRunner(pid_running=True, listener_up=False)
        runner.detected_listener_port = 9004
        engine = self._make_runtime_with_services(
            services=services,
            process_runner=runner,
        )
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--dashboard"], env={}))

        self.assertEqual(code, 0)
        rendered = out.getvalue()
        self.assertIn("Frontend: http://localhost:9004", rendered)
        self.assertIn("port: requested 9000 -> actual 9004", rendered)

    def test_dashboard_shows_listener_pid_details_when_available(self) -> None:
        services = {
            "Main Backend": ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd="/tmp/backend",
                pid=12345,
                requested_port=8000,
                actual_port=8000,
                status="running",
            ),
        }
        runner = _FakeOwnershipRunner(pid_running=True, listener_up=True)
        runner.listener_pid_map[8000] = [12345, 12346]
        engine = self._make_runtime_with_services(
            services=services,
            process_runner=runner,
        )

        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--dashboard"], env={}))

        self.assertEqual(code, 0)
        rendered = out.getvalue()
        self.assertIn("Listener PID: 12345,12346", rendered)

    def test_dashboard_keeps_projection_during_startup_grace_period(self) -> None:
        services = {
            "Main Frontend": ServiceRecord(
                name="Main Frontend",
                type="frontend",
                cwd="/tmp/frontend",
                pid=7777,
                requested_port=9000,
                actual_port=9000,
                status="running",
                started_at=time.time(),
            ),
        }
        engine = self._make_runtime_with_services(
            services=services,
            process_runner=_FakeOwnershipRunner(pid_running=True, listener_up=False),
        )
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--dashboard"], env={}))

        self.assertEqual(code, 0)
        rendered = out.getvalue()
        self.assertIn("Frontend: http://localhost:9000", rendered)
        self.assertIn("[Starting]", rendered)

    def test_health_returns_failure_when_n8n_requirement_is_unreachable(self) -> None:
        runner = _FakeTruthRunner(pid_running=True, listener_up=True)
        runner.wait_for_port_overrides[5678] = False
        engine = self._make_runtime_with_services(
            services={},
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    n8n={"enabled": True, "success": True, "final": 5678},
                    health="healthy",
                )
            },
            process_runner=runner,
        )
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--health"], env={}))

        self.assertEqual(code, 1)
        rendered = out.getvalue()
        self.assertIn("Dependencies", rendered)
        self.assertIn("n8n", rendered)
        self.assertIn("status=unreachable", rendered)
        self.assertIn("port=5678", rendered)

    def test_errors_reports_n8n_requirement_failures_from_runtime_truth(self) -> None:
        runner = _FakeTruthRunner(pid_running=True, listener_up=True)
        runner.wait_for_port_overrides[5678] = False
        engine = self._make_runtime_with_services(
            services={},
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    n8n={"enabled": True, "success": True, "final": 5678},
                    health="healthy",
                )
            },
            process_runner=runner,
        )
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--errors"], env={}))

        self.assertEqual(code, 1)
        self.assertIn("Main n8n: status=unreachable", out.getvalue())

    def test_health_returns_failure_when_postgres_requirement_is_unreachable(self) -> None:
        runner = _FakeTruthRunner(pid_running=True, listener_up=True)
        runner.wait_for_port_overrides[5432] = False
        engine = self._make_runtime_with_services(
            services={},
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    db={"enabled": True, "success": True, "final": 5432},
                    health="healthy",
                )
            },
            process_runner=runner,
        )
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--health"], env={}))

        self.assertEqual(code, 1)
        rendered = out.getvalue()
        self.assertIn("Dependencies", rendered)
        self.assertIn("postgres", rendered)
        self.assertIn("status=unreachable", rendered)
        self.assertIn("port=5432", rendered)

    def test_errors_reports_redis_requirement_failures_from_runtime_truth(self) -> None:
        runner = _FakeTruthRunner(pid_running=True, listener_up=True)
        runner.wait_for_port_overrides[6380] = False
        engine = self._make_runtime_with_services(
            services={},
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    redis={"enabled": True, "success": True, "final": 6380},
                    health="healthy",
                )
            },
            process_runner=runner,
        )
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--errors"], env={}))

        self.assertEqual(code, 1)
        self.assertIn("Main redis: status=unreachable", out.getvalue())

    def test_dashboard_shows_n8n_unreachable_when_live_probe_fails(self) -> None:
        runner = _FakeTruthRunner(pid_running=True, listener_up=True)
        runner.wait_for_port_overrides[5678] = False
        services = {
            "Main Backend": ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd="/tmp/backend",
                pid=9999,
                requested_port=8000,
                actual_port=8000,
                status="running",
            )
        }
        engine = self._make_runtime_with_services(
            services=services,
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    n8n={"enabled": True, "success": True, "final": 5678},
                    health="healthy",
                )
            },
            process_runner=runner,
        )
        out = StringIO()
        with redirect_stdout(out):
            code = engine.dispatch(parse_route(["--dashboard"], env={}))

        self.assertEqual(code, 0)
        self.assertIn("n8n: n/a [Unreachable]", out.getvalue())


if __name__ == "__main__":
    unittest.main()
