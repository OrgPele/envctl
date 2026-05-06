from __future__ import annotations

import time
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.service_manager import ServiceManager, ServiceStartDescriptor


class ServiceManagerTests(unittest.TestCase):
    def test_backend_retries_bind_conflict_and_updates_final_port(self) -> None:
        manager = ServiceManager()
        attempts: list[int] = []

        def start_backend(port: int) -> tuple[bool, str | None, int | None]:
            attempts.append(port)
            if len(attempts) == 1:
                return False, "bind: address already in use", None
            return True, None, 12001

        def reserve_next(port: int) -> int:
            return port

        service = manager.start_service_with_retry(
            project="Tree Alpha",
            service_type="backend",
            cwd="/tmp/tree-alpha/backend",
            requested_port=8000,
            start=start_backend,
            reserve_next=reserve_next,
            detect_actual=lambda _pid, requested: requested,
        )

        self.assertEqual(service.requested_port, 8000)
        self.assertEqual(service.actual_port, 8001)
        self.assertEqual(service.pid, 12001)
        self.assertEqual(attempts, [8000, 8001])

    def test_start_project_starts_backend_before_frontend_when_parallel_disabled(self) -> None:
        manager = ServiceManager()
        order: list[str] = []

        def start_backend(port: int) -> tuple[bool, str | None, int | None]:
            order.append(f"backend:{port}")
            return True, None, 22001

        def start_frontend(port: int) -> tuple[bool, str | None, int | None]:
            order.append(f"frontend:{port}")
            return True, None, 22002

        state = manager.start_project_with_attach(
            project="Tree Alpha",
            backend_port=8000,
            frontend_port=9000,
            backend_cwd="/tmp/tree-alpha/backend",
            frontend_cwd="/tmp/tree-alpha/frontend",
            start_backend=start_backend,
            start_frontend=start_frontend,
            reserve_next=lambda port: port,
            detect_backend_actual=lambda _pid, requested: requested,
            detect_frontend_actual=lambda _pid, requested: requested,
            parallel_start=False,
        )

        self.assertEqual(order, ["backend:8000", "frontend:9000"])
        self.assertEqual(state["Tree Alpha Backend"].actual_port, 8000)
        self.assertEqual(state["Tree Alpha Frontend"].actual_port, 9000)

    def test_start_project_parallel_mode_starts_services_concurrently(self) -> None:
        manager = ServiceManager()

        def start_backend(port: int) -> tuple[bool, str | None, int | None]:
            _ = port
            time.sleep(0.25)
            return True, None, 32001

        def start_frontend(port: int) -> tuple[bool, str | None, int | None]:
            _ = port
            time.sleep(0.25)
            return True, None, 32002

        started = time.monotonic()
        state = manager.start_project_with_attach(
            project="Tree Alpha",
            backend_port=8000,
            frontend_port=9000,
            backend_cwd="/tmp/tree-alpha/backend",
            frontend_cwd="/tmp/tree-alpha/frontend",
            start_backend=start_backend,
            start_frontend=start_frontend,
            reserve_next=lambda port: port,
            detect_backend_actual=lambda _pid, requested: requested,
            detect_frontend_actual=lambda _pid, requested: requested,
            parallel_start=True,
        )
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.45)
        self.assertEqual(state["Tree Alpha Backend"].pid, 32001)
        self.assertEqual(state["Tree Alpha Frontend"].pid, 32002)

    def test_parallel_attach_reports_first_descriptor_failure_deterministically(self) -> None:
        manager = ServiceManager()
        release_frontend = False

        def start_backend(_port: int) -> tuple[bool, str | None, int | None]:
            return True, None, 33001

        def start_frontend(_port: int) -> tuple[bool, str | None, int | None]:
            while not release_frontend:
                time.sleep(0.001)
            return True, None, 33002

        def fail_backend(_pid: int | None, _requested: int) -> int:
            nonlocal release_frontend
            release_frontend = True
            time.sleep(0.05)
            raise RuntimeError("backend listener not detected")

        descriptors = (
            ServiceStartDescriptor(
                service_type="backend",
                cwd="/tmp/tree-alpha/backend",
                requested_port=8000,
                start=start_backend,
                detect_actual=fail_backend,
                max_retries=0,
            ),
            ServiceStartDescriptor(
                service_type="frontend",
                cwd="/tmp/tree-alpha/frontend",
                requested_port=9000,
                start=start_frontend,
                detect_actual=lambda _pid, _requested: (_ for _ in ()).throw(
                    RuntimeError("frontend listener not detected")
                ),
                max_retries=0,
            ),
        )

        with self.assertRaisesRegex(Exception, "backend listener not detected"):
            manager.start_services_with_attach(
                project="Tree Alpha",
                descriptors=descriptors,
                reserve_next=lambda port: port,
                parallel_start=True,
            )

    def test_listener_detection_failure_retries_with_next_port(self) -> None:
        manager = ServiceManager()
        attempts: list[int] = []
        terminated: list[int] = []

        manager.terminate_process_group = lambda pid, **kwargs: terminated.append(pid) or True  # type: ignore[attr-defined]

        def start_backend(port: int) -> tuple[bool, str | None, int | None]:
            attempts.append(port)
            return True, None, 23001

        detect_calls = {"count": 0}

        def detect_actual(_pid: int | None, requested: int) -> int:
            detect_calls["count"] += 1
            if detect_calls["count"] == 1:
                raise RuntimeError("backend listener not detected")
            return requested

        service = manager.start_service_with_retry(
            project="Tree Alpha",
            service_type="backend",
            cwd="/tmp/tree-alpha/backend",
            requested_port=8000,
            start=start_backend,
            reserve_next=lambda port: port,
            detect_actual=detect_actual,
        )

        self.assertEqual(attempts, [8000, 8001])
        self.assertEqual(service.actual_port, 8001)
        self.assertEqual(terminated, [23001])

    def test_retry_callback_receives_service_retry_metadata(self) -> None:
        manager = ServiceManager()
        attempts: list[int] = []
        retries: list[tuple[str, int, int, int, str | None]] = []

        def start_backend(port: int) -> tuple[bool, str | None, int | None]:
            attempts.append(port)
            if len(attempts) == 1:
                return False, "bind: address already in use", None
            return True, None, 24001

        service = manager.start_service_with_retry(
            project="Tree Alpha",
            service_type="backend",
            cwd="/tmp/tree-alpha/backend",
            requested_port=8000,
            start=start_backend,
            reserve_next=lambda port: port,
            detect_actual=lambda _pid, requested: requested,
            on_retry=lambda service_type, failed_port, retry_port, attempt, error: retries.append(
                (service_type, failed_port, retry_port, attempt, error)
            ),
        )

        self.assertEqual(service.actual_port, 8001)
        self.assertEqual(retries, [("backend", 8000, 8001, 1, "bind: address already in use")])

    def test_non_listener_service_can_start_without_persisted_ports(self) -> None:
        manager = ServiceManager()

        service = manager.start_service_with_retry(
            project="Tree Alpha",
            service_type="backend",
            cwd="/tmp/tree-alpha/backend",
            requested_port=8000,
            start=lambda _port: (True, None, 25001),
            reserve_next=lambda port: port,
            detect_actual=lambda _pid, _requested: None,
            listener_expected=False,
        )

        self.assertFalse(service.listener_expected)
        self.assertIsNone(service.requested_port)
        self.assertIsNone(service.actual_port)


    def test_start_services_with_attach_returns_degraded_record_for_noncritical_failure(self) -> None:
        manager = ServiceManager()
        descriptors = (
            ServiceStartDescriptor(
                service_type="voice-runtime",
                cwd="/tmp/repo/voice-runtime",
                requested_port=8010,
                start=lambda _port: (False, "boot failed", None),
                listener_expected=True,
                critical=False,
                log_path="/tmp/run/voice.log",
                public_url="https://voice.example.test",
                health_url="https://voice.example.test/readyz",
                max_retries=0,
            ),
        )

        records = manager.start_services_with_attach(
            project="Main",
            descriptors=descriptors,
            reserve_next=lambda port: port,
        )

        record = records["Main Voice Runtime"]
        self.assertEqual(record.status, "degraded")
        self.assertFalse(record.critical)
        self.assertTrue(record.degraded)
        self.assertEqual(record.failure_detail, "Failed to start Main voice-runtime on port 8010: boot failed")
        self.assertEqual(record.log_path, "/tmp/run/voice.log")
        self.assertEqual(record.public_url, "https://voice.example.test")
        self.assertEqual(record.health_url, "https://voice.example.test/readyz")

    def test_start_services_with_attach_records_descriptor_metadata_on_success(self) -> None:
        manager = ServiceManager()
        records = manager.start_services_with_attach(
            project="Main",
            descriptors=(
                ServiceStartDescriptor(
                    service_type="voice-runtime",
                    cwd="/tmp/repo/voice-runtime",
                    requested_port=8010,
                    start=lambda _port: (True, None, 44001),
                    detect_actual=lambda _pid, requested: requested + 2,
                    log_path="/tmp/run/voice.log",
                    public_url="https://voice.example.test",
                    health_url="https://voice.example.test/readyz",
                ),
            ),
            reserve_next=lambda port: port,
        )

        record = records["Main Voice Runtime"]
        self.assertEqual(record.actual_port, 8012)
        self.assertEqual(record.service_slug, "voice-runtime")
        self.assertEqual(record.project, "Main")
        self.assertEqual(record.log_path, "/tmp/run/voice.log")
        self.assertEqual(record.public_url, "https://voice.example.test")
        self.assertEqual(record.health_url, "https://voice.example.test/readyz")

    def test_start_services_with_attach_starts_arbitrary_services_and_non_listeners(self) -> None:
        manager = ServiceManager()
        order: list[str] = []

        descriptors = (
            ServiceStartDescriptor(
                service_type="backend",
                cwd="/tmp/repo/backend",
                requested_port=8000,
                start=lambda port: order.append(f"backend:{port}") or (True, None, 31001),
                detect_actual=lambda _pid, requested: requested,
            ),
            ServiceStartDescriptor(
                service_type="voice-runtime",
                cwd="/tmp/repo/voice-runtime",
                requested_port=8010,
                start=lambda port: order.append(f"voice-runtime:{port}") or (True, None, 31002),
                detect_actual=lambda _pid, requested: requested,
            ),
            ServiceStartDescriptor(
                service_type="worker",
                cwd="/tmp/repo/backend",
                requested_port=0,
                start=lambda port: order.append(f"worker:{port}") or (True, None, 31003),
                detect_actual=lambda _pid, _requested: None,
                listener_expected=False,
            ),
        )

        records = manager.start_services_with_attach(
            project="Main",
            descriptors=descriptors,
            reserve_next=lambda port: port,
            parallel_start=False,
        )

        self.assertEqual(order, ["backend:8000", "voice-runtime:8010", "worker:0"])
        self.assertEqual(records["Main Backend"].actual_port, 8000)
        self.assertEqual(records["Main Voice Runtime"].actual_port, 8010)
        self.assertFalse(records["Main Worker"].listener_expected)
        self.assertIsNone(records["Main Worker"].requested_port)
        self.assertIsNone(records["Main Worker"].actual_port)

    def test_start_services_with_attach_cleans_partial_records_on_failure(self) -> None:
        manager = ServiceManager()
        terminated: list[int] = []
        manager.terminate_process_group = lambda pid, **kwargs: terminated.append(pid) or True  # type: ignore[attr-defined]

        descriptors = (
            ServiceStartDescriptor(
                service_type="backend",
                cwd="/tmp/repo/backend",
                requested_port=8000,
                start=lambda _port: (True, None, 41001),
                detect_actual=lambda _pid, requested: requested,
            ),
            ServiceStartDescriptor(
                service_type="voice-runtime",
                cwd="/tmp/repo/voice-runtime",
                requested_port=8010,
                start=lambda _port: (False, "bind: address already in use", None),
                detect_actual=lambda _pid, requested: requested,
                max_retries=0,
            ),
        )

        with self.assertRaisesRegex(Exception, "Failed to start Main voice-runtime"):
            manager.start_services_with_attach(
                project="Main",
                descriptors=descriptors,
                reserve_next=lambda port: port,
            )

        self.assertEqual(terminated, [41001])


if __name__ == "__main__":
    unittest.main()
