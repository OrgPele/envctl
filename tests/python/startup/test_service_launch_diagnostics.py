from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace

from envctl_engine.startup.service_execution import PreparedServiceLaunch
from envctl_engine.startup.service_launch_diagnostics import record_runtime_launch_diagnostics


class ServiceLaunchDiagnosticsTests(unittest.TestCase):
    def test_records_backend_cors_and_frontend_launch_payloads(self) -> None:
        route = SimpleNamespace(flags={})
        runtime = SimpleNamespace(env={}, config=SimpleNamespace(raw={}))
        launches = {
            "backend": PreparedServiceLaunch(
                service_name="backend",
                cwd=Path("/repo/backend"),
                log_path="/tmp/backend.log",
                requested_port=8000,
                env={"FRONTEND_BASE_URL": "http://localhost:3000", "CORS_ORIGINS_RAW": "http://localhost:3000"},
                command_source="configured",
            ),
            "frontend": PreparedServiceLaunch(
                service_name="frontend",
                cwd=Path("/repo/frontend"),
                log_path="/tmp/frontend.log",
                requested_port=3000,
                env={"VITE_BACKEND_URL": "http://localhost:8000"},
                command_source="configured",
            ),
        }

        record_runtime_launch_diagnostics(
            route=route,
            runtime=runtime,
            project_name="Main",
            frontend_port=3000,
            backend_env={"FRONTEND_BASE_URL": "http://localhost:3000", "CORS_ORIGINS_RAW": "http://localhost:3000"},
            prepared_launches=launches,
            backend_command_source="configured",
            frontend_command_source="configured",
        )

        payload = route.flags["_runtime_launch_diagnostics"]["Main"]
        self.assertTrue(payload["backend"]["cors"]["projected"])
        self.assertEqual(payload["backend"]["cors"]["frontend_origin"], "http://localhost:3000")
        self.assertIn("VITE_BACKEND_URL", payload["frontend"]["env"])

    def test_skips_when_no_prepared_launches_exist(self) -> None:
        route = SimpleNamespace(flags={})
        runtime = SimpleNamespace(env={}, config=SimpleNamespace(raw={}))

        record_runtime_launch_diagnostics(
            route=route,
            runtime=runtime,
            project_name="Main",
            frontend_port=0,
            backend_env={},
            prepared_launches={},
            backend_command_source=None,
            frontend_command_source=None,
        )

        self.assertEqual(route.flags, {})


if __name__ == "__main__":
    unittest.main()
