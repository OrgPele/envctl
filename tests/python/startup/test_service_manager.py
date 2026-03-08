from __future__ import annotations

import time
import unittest
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.service_manager import ServiceManager


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

    def test_listener_detection_failure_retries_with_next_port(self) -> None:
        manager = ServiceManager()
        attempts: list[int] = []

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


if __name__ == "__main__":
    unittest.main()
