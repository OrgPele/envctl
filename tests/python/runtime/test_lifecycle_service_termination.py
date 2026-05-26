from __future__ import annotations

import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from envctl_engine.runtime.lifecycle_service_termination import (
    service_port,
    terminate_service_record,
    terminate_services_from_state,
    terminate_started_services,
)
from envctl_engine.state.models import RunState, ServiceRecord


class LifecycleServiceTerminationTests(unittest.TestCase):
    def test_terminate_started_services_uses_non_aggressive_unverified_shutdown(self) -> None:
        calls: list[tuple[int, bool, bool]] = []
        runtime = SimpleNamespace(
            _terminate_service_record=lambda service, *, aggressive, verify_ownership: calls.append(
                (service.pid, aggressive, verify_ownership)
            )
            or True
        )

        terminate_started_services(
            runtime,
            {
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1),
                "Main Frontend": ServiceRecord(name="Main Frontend", type="frontend", cwd=".", pid=2),
            },
        )

        self.assertEqual(calls, [(1, False, False), (2, False, False)])

    def test_terminate_services_from_state_filters_selected_services_and_releases_terminated_ports(self) -> None:
        released: list[int] = []
        terminated: list[tuple[int, bool, bool]] = []
        runtime = SimpleNamespace(
            port_planner=SimpleNamespace(release=lambda port: released.append(port)),
            _terminate_service_record=lambda service, *, aggressive, verify_ownership: terminated.append(
                (service.pid, aggressive, verify_ownership)
            )
            or True,
        )
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1, actual_port=8000),
                "Main Frontend": ServiceRecord(
                    name="Main Frontend", type="frontend", cwd=".", pid=2, requested_port=3000
                ),
            },
        )

        terminate_services_from_state(
            runtime,
            state,
            selected_services={"Main Frontend"},
            aggressive=True,
            verify_ownership=True,
        )

        self.assertEqual(terminated, [(2, True, True)])
        self.assertEqual(released, [3000])

    def test_terminate_service_record_skips_self_parent_and_missing_ownership_port(self) -> None:
        events: list[dict[str, object]] = []
        runtime = SimpleNamespace(
            _emit=lambda _event, **payload: events.append(payload),
            process_runner=SimpleNamespace(),
        )

        with patch.object(os, "getpid", return_value=100), patch.object(os, "getppid", return_value=200):
            self.assertFalse(
                terminate_service_record(
                    runtime,
                    SimpleNamespace(name="Self", pid=100, actual_port=8000),
                    aggressive=False,
                    verify_ownership=False,
                )
            )
        self.assertFalse(
            terminate_service_record(
                runtime,
                SimpleNamespace(name="No Port", pid=300, actual_port=None, requested_port=None),
                aggressive=False,
                verify_ownership=True,
            )
        )

        self.assertEqual(events[0]["reason"], "self_or_parent")
        self.assertEqual(events[1]["reason"], "missing_port_for_ownership")

    def test_terminate_service_record_accepts_verified_listener_child_and_prefers_process_group(self) -> None:
        calls: list[tuple[str, int]] = []

        def pid_owns_port(pid: int, port: int) -> bool:
            return pid == 222 and port == 9000

        runtime = SimpleNamespace(
            _emit=lambda *_args, **_kwargs: None,
            process_runner=SimpleNamespace(
                pid_owns_port=pid_owns_port,
                terminate_process_group=lambda pid, **_kwargs: calls.append(("group", pid)) or True,
                terminate=lambda pid, **_kwargs: calls.append(("single", pid)) or True,
            ),
        )

        terminated = terminate_service_record(
            runtime,
            SimpleNamespace(name="Main Frontend", pid=111, actual_port=9000, listener_pids=[222]),
            aggressive=False,
            verify_ownership=True,
        )

        self.assertTrue(terminated)
        self.assertEqual(calls, [("group", 111)])

    def test_service_port_prefers_actual_then_requested(self) -> None:
        self.assertEqual(service_port(SimpleNamespace(actual_port=9000, requested_port=8000)), 9000)
        self.assertEqual(service_port(SimpleNamespace(actual_port=None, requested_port=8000)), 8000)
        self.assertIsNone(service_port(SimpleNamespace(actual_port=None, requested_port=None)))


if __name__ == "__main__":
    unittest.main()
