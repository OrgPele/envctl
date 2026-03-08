from __future__ import annotations

import unittest
from pathlib import Path
import sys
from types import SimpleNamespace

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.shared.process_probe import ProcessProbe


class _FakeRunner:
    def __init__(self) -> None:
        self._running = True

    def is_pid_running(self, _pid: int) -> bool:
        return self._running

    def wait_for_pid_port(
        self,
        _pid: int,
        _port: int,
        *,
        host: str = "127.0.0.1",
        timeout: float = 30.0,
        debug_pid_wait_group: str = "",
    ) -> bool:  # noqa: ARG002
        _ = host, debug_pid_wait_group
        return True

    def wait_for_port(self, _port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:  # noqa: ARG002
        _ = host
        return False


class ProcessProbeContractTests(unittest.TestCase):
    def test_parse_lsof_listener_pid_map(self) -> None:
        stdout = (
            "COMMAND   PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
            "python3 123 user 10u IPv4 0x0 0t0 TCP *:8000 (LISTEN)\n"
            "python3 456 user 10u IPv4 0x0 0t0 TCP *:9000 (LISTEN)\n"
        )
        parsed = ProcessProbe.parse_lsof_listener_pid_map(stdout=stdout, target_ports={8000, 9000, 9100})
        self.assertEqual(parsed, {123: {8000}, 456: {9000}})

    def test_split_listener_pid_maps(self) -> None:
        kill, docker = ProcessProbe.split_listener_pid_maps(
            pid_port_map={111: {8000}, 222: {9000}},
            command_for_pid=lambda pid: "docker-proxy" if pid == 222 else "python app.py",
            is_docker_process=lambda cmd: "docker" in cmd,
        )
        self.assertEqual(kill, {111: {8000}})
        self.assertEqual(docker, {222: {9000}})

    def test_service_truth_status_uses_pid_probe_success(self) -> None:
        runner = _FakeRunner()
        probe = ProcessProbe(runner)
        service = SimpleNamespace(pid=101, actual_port=8000, requested_port=8000, name="svc")
        events: list[dict[str, object]] = []

        status = probe.service_truth_status(
            service=service,
            listener_truth_enforced=True,
            service_truth_timeout=0.1,
            within_startup_grace=lambda _service: False,
            truth_discovery=lambda _service, _port: None,
            clear_listener_pids=lambda _service: None,
            refresh_listener_pids=lambda _service, _port: None,
            emit=lambda event, **payload: events.append({"event": event, **payload}),
            rebind_stale=lambda _service, _pid: False,
        )

        self.assertEqual(status, "running")
        self.assertEqual(events, [])

    def test_service_truth_status_falls_back_to_port_probe_when_enabled(self) -> None:
        runner = _FakeRunner()
        probe = ProcessProbe(runner)
        service = SimpleNamespace(pid=101, actual_port=8000, requested_port=8000, name="svc")
        events: list[dict[str, object]] = []

        runner.wait_for_pid_port = (
            lambda _pid, _port, *, host="127.0.0.1", timeout=30.0, debug_pid_wait_group="": False
        )  # type: ignore[assignment]
        runner.wait_for_port = lambda _port, *, host="127.0.0.1", timeout=30.0: True  # type: ignore[assignment]

        status = probe.service_truth_status(
            service=service,
            listener_truth_enforced=True,
            service_truth_timeout=0.1,
            within_startup_grace=lambda _service: False,
            truth_discovery=lambda _service, _port: None,
            clear_listener_pids=lambda _service: None,
            refresh_listener_pids=lambda _service, _port: None,
            emit=lambda event, **payload: events.append({"event": event, **payload}),
            fallback_enabled=True,
            rebind_stale=lambda _service, _pid: False,
        )

        self.assertEqual(status, "running")
        self.assertEqual(events[0]["event"], "service.truth.degraded")


if __name__ == "__main__":
    unittest.main()
