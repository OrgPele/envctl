from __future__ import annotations

from types import SimpleNamespace
import unittest

from envctl_engine.state.action_health_support import StateActionHealthSupport
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord


class _HealthSupportHarness(StateActionHealthSupport):
    def __init__(self) -> None:
        self.runtime = SimpleNamespace(
            env={},
            project_name_from_service=lambda service_name: str(service_name).split(" ", 1)[0],
        )

    def _parallel_service_map(self, services, mapper):  # noqa: ANN001
        return [mapper(service) for service in services]


class StateActionHealthSupportTests(unittest.TestCase):
    def test_health_rows_project_services_and_dependencies(self) -> None:
        support = _HealthSupportHarness()
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main backend": ServiceRecord(
                    name="Main backend",
                    type="backend",
                    cwd="/repo",
                    status="running",
                    actual_port=8000,
                    project="Main",
                    service_slug="backend",
                )
            },
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    redis={"enabled": True, "success": True, "final": 6380},
                )
            },
        )

        service_rows = support._health_service_rows(state)
        dependency_rows = support._requirement_health_rows(state)

        self.assertEqual(service_rows[0]["project"], "Main")
        self.assertEqual(service_rows[0]["name"], "Main backend")
        self.assertEqual(service_rows[0]["port"], 8000)
        self.assertEqual(dependency_rows[0]["component"], "redis")
        self.assertEqual(dependency_rows[0]["status"], "healthy")
        self.assertEqual(dependency_rows[0]["port"], 6380)

    def test_health_payload_separates_optional_degraded_from_blocking_failures(self) -> None:
        support = _HealthSupportHarness()
        state = RunState(run_id="run-1", mode="main")
        service_rows = [
            {
                "project": "Main",
                "name": "Main frontend",
                "type": "frontend",
                "service_slug": "frontend",
                "status": "starting",
                "critical": False,
                "degraded": True,
            },
            {
                "project": "Main",
                "name": "Main backend",
                "type": "backend",
                "service_slug": "backend",
                "status": "failed",
                "critical": True,
                "degraded": False,
            },
        ]
        dependency_rows = [{"project": "Main", "component": "redis", "status": "healthy", "port": 6380}]

        payload = support._health_payload(
            state=state,
            service_rows=service_rows,
            dependency_rows=dependency_rows,
            status_counts=support._health_status_counts(
                service_rows=service_rows,
                dependency_rows=dependency_rows,
            ),
            recent_failures=[],
            failing_services=[],
            requirement_issues=[],
            total_projects=1,
            strict=True,
        )

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["overall"], "unhealthy")
        self.assertEqual(payload["optional_failures"], ["frontend"])
        self.assertEqual(payload["critical_failures"], ["Main backend"])
        self.assertTrue(payload["strict_blocking"])


if __name__ == "__main__":
    unittest.main()
