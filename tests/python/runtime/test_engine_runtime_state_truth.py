from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.engine_runtime_state_truth import (  # noqa: E402
    reconcile_project_requirement_truth,
    reconcile_requirements_truth,
    reconcile_state_truth,
    requirement_component_port,
    requirement_runtime_status,
    requirement_truth_issues,
    state_fingerprint,
)
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord  # noqa: E402


class EngineRuntimeStateTruthTests(unittest.TestCase):
    def test_state_fingerprint_changes_when_state_changes(self) -> None:
        first = RunState(run_id="run-1", mode="main", services={})
        second = RunState(
            run_id="run-1",
            mode="main",
            services={"Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".")},
        )

        self.assertNotEqual(state_fingerprint(first), state_fingerprint(second))

    def test_requirement_component_port_prefers_final_then_requested(self) -> None:
        self.assertEqual(requirement_component_port({"final": 5433, "requested": 5432}), 5433)
        self.assertEqual(requirement_component_port({"requested": 5432}), 5432)

    def test_requirement_runtime_status_variants(self) -> None:
        process_runner = SimpleNamespace(wait_for_port=lambda port, timeout: port == 5432)
        runtime = SimpleNamespace(
            process_runner=process_runner,
            _listener_truth_enforced=lambda: True,
            _service_truth_timeout=lambda: 1.0,
        )
        req = RequirementsResult(project="Main")

        self.assertEqual(
            requirement_runtime_status(
                runtime,
                component_name="postgres",
                component_data={"enabled": False},
                requirements=req,
            ),
            "disabled",
        )
        self.assertEqual(
            requirement_runtime_status(
                runtime,
                component_name="postgres",
                component_data={"enabled": True, "simulated": True},
                requirements=req,
            ),
            "simulated",
        )
        self.assertEqual(
            requirement_runtime_status(
                runtime,
                component_name="postgres",
                component_data={"enabled": True, "success": False},
                requirements=req,
            ),
            "starting",
        )
        req.failures.append("db failed")
        self.assertEqual(
            requirement_runtime_status(
                runtime,
                component_name="postgres",
                component_data={"enabled": True, "success": False},
                requirements=req,
            ),
            "unhealthy",
        )
        self.assertEqual(
            requirement_runtime_status(
                runtime,
                component_name="postgres",
                component_data={"enabled": True, "success": True, "final": 5432},
                requirements=req,
            ),
            "healthy",
        )

    def test_requirement_runtime_status_uses_expected_container_ownership(self) -> None:
        class _Runner:
            def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                args = tuple(cmd)
                if args[:4] == ("docker", "ps", "-a", "--filter"):
                    return SimpleNamespace(returncode=0, stdout="envctl-redis-main-deadbeef\n", stderr="")
                if args[:3] == ("docker", "port", "envctl-redis-main-deadbeef"):
                    return SimpleNamespace(returncode=0, stdout="", stderr="")
                return SimpleNamespace(returncode=0, stdout="running\n", stderr="")

            def wait_for_port(self, port, timeout):  # noqa: ANN001
                _ = timeout
                return port == 6382

        runtime = SimpleNamespace(
            process_runner=_Runner(),
            _listener_truth_enforced=lambda: True,
            _service_truth_timeout=lambda: 1.0,
        )
        req = RequirementsResult(project="Main")
        self.assertEqual(
            requirement_runtime_status(
                runtime,
                project="Main",
                project_root=Path("/tmp/project"),
                component_name="redis",
                component_data={
                    "enabled": True,
                    "success": True,
                    "final": 6382,
                    "container_name": "envctl-redis-main-deadbeef",
                },
                requirements=req,
            ),
            "unreachable",
        )
        self.assertEqual(
            requirement_runtime_status(
                runtime,
                component_name="postgres",
                component_data={"enabled": True, "success": True, "final": 9999},
                requirements=req,
            ),
            "unreachable",
        )
        self.assertEqual(
            requirement_runtime_status(
                runtime,
                component_name="supabase",
                component_data={"enabled": True, "success": True},
                requirements=req,
            ),
            "healthy",
        )

    def test_reconcile_project_requirement_truth_updates_runtime_status_and_issues(self) -> None:
        runtime = SimpleNamespace(
            process_runner=SimpleNamespace(wait_for_port=lambda port, timeout: port == 5432),
            _listener_truth_enforced=lambda: True,
            _service_truth_timeout=lambda: 1.0,
        )
        requirements = RequirementsResult(
            project="Main",
            db={"enabled": True, "success": True, "final": 5432},
            redis={"enabled": True, "success": True, "final": 6390},
            n8n={"enabled": False},
        )

        issues = reconcile_project_requirement_truth(runtime, "Main", requirements)

        self.assertEqual(requirements.db["runtime_status"], "healthy")
        self.assertEqual(requirements.redis["runtime_status"], "unreachable")
        self.assertEqual(requirements.n8n["runtime_status"], "disabled")
        self.assertEqual(
            issues,
            [{"project": "Main", "component": "redis", "status": "unreachable", "port": 6390}],
        )

    def test_requirement_truth_issues_reconciles_when_runtime_status_missing(self) -> None:
        runtime = SimpleNamespace(
            process_runner=SimpleNamespace(wait_for_port=lambda port, timeout: True),
            _listener_truth_enforced=lambda: True,
            _service_truth_timeout=lambda: 1.0,
        )
        state = RunState(
            run_id="run-1",
            mode="main",
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    db={"enabled": True, "success": True, "final": 5432},
                )
            },
        )

        issues = requirement_truth_issues(runtime, state)

        self.assertEqual(issues, [])
        self.assertEqual(state.requirements["Main"].db["runtime_status"], "healthy")

    def test_reconcile_requirements_truth_accumulates_projects(self) -> None:
        runtime = SimpleNamespace(
            process_runner=SimpleNamespace(wait_for_port=lambda port, timeout: False),
            _listener_truth_enforced=lambda: True,
            _service_truth_timeout=lambda: 1.0,
        )
        state = RunState(
            run_id="run-1",
            mode="main",
            requirements={
                "Main": RequirementsResult(project="Main", db={"enabled": True, "success": True, "final": 5432}),
                "Other": RequirementsResult(project="Other", redis={"enabled": True, "success": False}),
            },
        )

        issues = reconcile_requirements_truth(runtime, state)

        self.assertEqual(
            issues,
            [
                {"project": "Main", "component": "postgres", "status": "unreachable", "port": 5432},
                {"project": "Other", "component": "redis", "status": "starting", "port": None},
            ],
        )

    def test_reconcile_state_truth_updates_services_and_emits_anomaly(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        anomalies: list[dict[str, object]] = []
        service = ServiceRecord(name="Main Backend", type="backend", cwd=".", status="unknown")
        state = RunState(
            run_id="run-1",
            mode="main",
            services={"Main Backend": service},
            requirements={"Main": RequirementsResult(project="Main", db={"enabled": True, "success": False})},
        )

        runtime = SimpleNamespace(
            _emit=lambda event, **payload: events.append((event, payload)),
            _service_truth_status=lambda _service: "stale",
            process_runner=SimpleNamespace(wait_for_port=lambda port, timeout: False),
            _listener_truth_enforced=lambda: True,
            _service_truth_timeout=lambda: 1.0,
            _debug_recorder=SimpleNamespace(append_anomaly=lambda anomaly: anomalies.append(anomaly)),
        )

        failing = reconcile_state_truth(runtime, state)

        self.assertEqual(failing, ["Main Backend"])
        self.assertEqual(service.status, "stale")
        self.assertEqual(state.requirements["Main"].db["runtime_status"], "starting")
        self.assertEqual(events[0][0], "state.fingerprint.before_reconcile")
        self.assertEqual(events[1][0], "state.fingerprint.after_reconcile")
        self.assertEqual(anomalies, [])

    def test_reconcile_state_truth_overlaps_service_and_requirement_checks(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        service_started = threading.Event()
        requirement_started = threading.Event()
        release_service = threading.Event()
        service = ServiceRecord(name="Main Backend", type="backend", cwd=".", status="unknown")
        state = RunState(
            run_id="run-1",
            mode="main",
            services={"Main Backend": service},
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    db={"enabled": True, "success": True, "final": 5432},
                )
            },
        )

        def _service_truth_status(_service: object) -> str:
            service_started.set()
            self.assertTrue(release_service.wait(timeout=1.0))
            return "running"

        def _wait_for_port(_port: int, timeout: float) -> bool:
            _ = timeout
            requirement_started.set()
            return True

        runtime = SimpleNamespace(
            _emit=lambda event_name, **payload: events.append((event_name, payload)),
            _service_truth_status=_service_truth_status,
            process_runner=SimpleNamespace(wait_for_port=_wait_for_port),
            _listener_truth_enforced=lambda: True,
            _service_truth_timeout=lambda: 1.0,
            _debug_recorder=None,
        )

        result_holder: dict[str, object] = {}

        def _run() -> None:
            result_holder["failing"] = reconcile_state_truth(runtime, state)

        thread = threading.Thread(target=_run)
        thread.start()
        self.assertTrue(service_started.wait(timeout=1.0))
        self.assertTrue(requirement_started.wait(timeout=1.0))
        release_service.set()
        thread.join(timeout=1.0)

        self.assertFalse(thread.is_alive())
        self.assertEqual(result_holder.get("failing"), [])
        self.assertEqual(state.requirements["Main"].db["runtime_status"], "healthy")


if __name__ == "__main__":
    unittest.main()
