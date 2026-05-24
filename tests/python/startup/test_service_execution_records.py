from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.startup.service_execution_records import (
    PreparedServiceLaunch,
    finalize_launched_service_records,
)
from envctl_engine.state.models import ServiceRecord


class ServiceExecutionRecordsTests(unittest.TestCase):
    def test_finalizes_core_and_additional_service_records(self) -> None:
        backend_plan = SimpleNamespace(final=8000)
        frontend_plan = SimpleNamespace(final=5173)
        worker_plan = SimpleNamespace(final=9000)
        context = SimpleNamespace(
            name="Main",
            ports={"backend": backend_plan, "frontend": frontend_plan, "worker": worker_plan},
        )
        worker = SimpleNamespace(name="worker", env_suffix="WORKER")
        prepared_launches = {
            "backend": PreparedServiceLaunch(
                service_name="backend",
                cwd="/repo/backend",
                log_path="/logs/backend.txt",
                requested_port=8000,
                env={},
                command_source="configured",
            ),
            "frontend": PreparedServiceLaunch(
                service_name="frontend",
                cwd="/repo/frontend",
                log_path="/logs/frontend.txt",
                requested_port=5173,
                env={},
                command_source="configured",
            ),
            "worker": PreparedServiceLaunch(
                service_name="worker",
                cwd="/repo/worker",
                log_path="/logs/worker.txt",
                requested_port=9000,
                env={},
                command_source="configured",
            ),
        }
        records = {
            "Main Backend": ServiceRecord(
                name="Main Backend",
                type="backend",
                cwd="/repo/backend",
                project="Main",
                requested_port=8000,
                actual_port=8100,
                pid=101,
            ),
            "Main Frontend": ServiceRecord(
                name="Main Frontend",
                type="frontend",
                cwd="/repo/frontend",
                project="Main",
                requested_port=5173,
                actual_port=5273,
                pid=102,
            ),
            "Main Worker": ServiceRecord(
                name="Main Worker",
                type="worker",
                cwd="/repo/worker",
                project="Main",
                requested_port=9000,
                actual_port=9100,
                pid=103,
            ),
        }

        launched = finalize_launched_service_records(
            context=context,
            records=records,
            backend_plan=backend_plan,
            frontend_plan=frontend_plan,
            additional_services=(worker,),
            prepared_launches=prepared_launches,
            backend_log_path="/logs/backend.txt",
            frontend_log_path="/logs/frontend.txt",
            project_env_for_service=lambda service_name: {
                "ENVCTL_SOURCE_SERVICE_WORKER_PUBLIC_URL": "http://worker.local",
                "ENVCTL_SOURCE_SERVICE_WORKER_HEALTH_URL": "http://worker.local/health",
            }
            if service_name == "worker"
            else {},
        )

        self.assertEqual(backend_plan.final, 8100)
        self.assertEqual(frontend_plan.final, 5273)
        self.assertEqual(worker_plan.final, 9100)
        self.assertEqual(records["Main Backend"].log_path, "/logs/backend.txt")
        self.assertEqual(records["Main Frontend"].log_path, "/logs/frontend.txt")
        self.assertEqual(records["Main Worker"].log_path, "/logs/worker.txt")
        self.assertEqual(records["Main Worker"].public_url, "http://worker.local")
        self.assertEqual(records["Main Worker"].health_url, "http://worker.local/health")
        self.assertEqual([runtime.service_name for runtime in launched], ["backend", "frontend", "worker"])
        self.assertEqual([runtime.actual_port for runtime in launched], [8100, 5273, 9100])


if __name__ == "__main__":
    unittest.main()
