from __future__ import annotations

import tempfile
from pathlib import Path

from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime

from tests.python.runtime.engine_runtime_real_startup_test_support import (
    _EngineRuntimeRealStartupTestCase,
    _FakeProcessRunner,
)


class EngineRuntimePlanParallelStartupTests(_EngineRuntimeRealStartupTestCase):
    def test_plan_mode_defaults_to_parallel_startup_execution(self) -> None:
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
            route = parse_route(["--plan", "feature-a,feature-b", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "parallel")
            self.assertEqual(latest.get("workers"), 2)

    def test_plan_mode_parallel_default_caps_workers_at_four(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            for branch in ("feature-a", "feature-b", "feature-c", "feature-d", "feature-e", "feature-f"):
                (repo / "trees" / branch / "1").mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            engine.port_planner.availability_checker = lambda _port: True
            fake_runner = _FakeProcessRunner()
            fake_runner.wait_for_port_result = True
            fake_runner.wait_for_pid_port_result = True
            engine.process_runner = fake_runner  # type: ignore[attr-defined]
            route = parse_route(
                ["--plan", "feature-a,feature-b,feature-c,feature-d,feature-e,feature-f", "--batch"],
                env={},
            )

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "parallel")
            self.assertEqual(latest.get("workers"), 4)

    def test_plan_ignores_parallel_trees_env_false_unless_explicitly_disabled(self) -> None:
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
            route = parse_route(["--plan", "feature-a,feature-b", "--batch"], env={})

            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            execution_events = [event for event in engine.events if event.get("event") == "startup.execution"]
            self.assertTrue(execution_events)
            latest = execution_events[-1]
            self.assertEqual(latest.get("mode"), "parallel")
            self.assertEqual(latest.get("workers"), 2)

