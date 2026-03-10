from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.engine_runtime_service_truth import (  # noqa: E402
    assert_project_services_post_start_truth,
    command_result_error_text,
    detect_service_actual_port,
    listener_pids_for_port,
    rebind_stale_service_pid,
    refresh_service_listener_pids,
    service_truth_fallback_enabled,
    service_truth_status,
    tail_log_error_line,
    wait_for_service_listener,
)


class _RunnerStub:
    def __init__(self) -> None:
        self.wait_for_pid_port_result = False
        self.wait_for_port_result = False
        self.find_pid_listener_port_result: int | None = None
        self.process_tree_probe_supported = True
        self.listener_pids_result: list[int] = []
        self.process_tree_listener_pids_result: list[int] = []
        self.running_result = True

    def wait_for_pid_port(
        self,
        pid: int,
        port: int,
        *,
        host: str = "127.0.0.1",
        timeout: float = 30.0,
        debug_pid_wait_group: str = "",
    ) -> bool:  # noqa: ARG002
        _ = host, debug_pid_wait_group
        return self.wait_for_pid_port_result

    def wait_for_port(self, port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:  # noqa: ARG002
        _ = host
        return self.wait_for_port_result

    def find_pid_listener_port(self, pid: int, requested_port: int, *, max_delta: int) -> int | None:  # noqa: ARG002
        return self.find_pid_listener_port_result

    def supports_process_tree_probe(self) -> bool:
        return self.process_tree_probe_supported

    def listener_pids_for_port(self, port: int) -> list[int]:  # noqa: ARG002
        return list(self.listener_pids_result)

    def process_tree_listener_pids(self, pid: int, port: int | None = None) -> list[int]:  # noqa: ARG002
        return list(self.process_tree_listener_pids_result)

    def is_pid_running(self, pid: int) -> bool:  # noqa: ARG002
        return self.running_result


class EngineRuntimeServiceTruthTests(unittest.TestCase):
    def test_command_result_error_text_prefers_stderr_then_stdout(self) -> None:
        stderr_value = command_result_error_text(
            result=SimpleNamespace(stderr="first\nsecond", stdout="", returncode=2)
        )
        stdout_value = command_result_error_text(result=SimpleNamespace(stderr="", stdout="a\nb", returncode=3))

        self.assertEqual(stderr_value, "second")
        self.assertEqual(stdout_value, "b")

    def test_tail_log_error_line_prefers_error_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "service.log"
            log_path.write_text("booting\nTraceback: boom\nhealthy?\n", encoding="utf-8")

            line = tail_log_error_line(str(log_path))

        self.assertEqual(line, "Traceback: boom")

    def test_wait_for_service_listener_uses_port_probe_fallback(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runner = _RunnerStub()
        runner.wait_for_port_result = True
        runtime = SimpleNamespace(
            process_runner=runner,
            config=SimpleNamespace(runtime_truth_mode="auto"),
            _listener_probe_supported=False,
            _service_listener_timeout=lambda: 2.0,
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        ok = wait_for_service_listener(runtime, 1234, 8000, service_name="Main Backend")

        self.assertTrue(ok)
        self.assertEqual(events[0][0], "service.bind.port_fallback")
        self.assertEqual(events[0][1]["service"], "Main Backend")

    def test_service_truth_fallback_enabled_respects_modes(self) -> None:
        strict_runtime = SimpleNamespace(
            config=SimpleNamespace(runtime_truth_mode="strict"),
            _listener_probe_supported=False,
            process_runner=_RunnerStub(),
        )
        best_effort_runtime = SimpleNamespace(
            config=SimpleNamespace(runtime_truth_mode="best_effort"),
            _listener_probe_supported=True,
            process_runner=_RunnerStub(),
        )

        self.assertFalse(service_truth_fallback_enabled(strict_runtime))
        self.assertTrue(service_truth_fallback_enabled(best_effort_runtime))

    def test_detect_service_actual_port_emits_discovery_when_rebound(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runner = _RunnerStub()
        runner.find_pid_listener_port_result = 8012
        runtime = SimpleNamespace(
            process_runner=runner,
            config=SimpleNamespace(runtime_truth_mode="auto"),
            _listener_probe_supported=True,
            _service_listener_timeout=lambda: 1.0,
            _service_rebound_max_delta=lambda: 50,
            _emit=lambda event, **payload: events.append((event, payload)),
        )

        discovered = detect_service_actual_port(runtime, pid=4321, requested_port=8000, service_name="Main Backend")

        self.assertEqual(discovered, 8012)
        self.assertEqual(events[0][0], "service.bind.actual.discovered")
        self.assertEqual(events[0][1]["discovered_port"], 8012)

    def test_listener_pids_for_port_and_refresh_listener_pids(self) -> None:
        runner = _RunnerStub()
        runner.listener_pids_result = [42, 41, 42]
        runner.process_tree_listener_pids_result = [55, 54, 55]
        runtime = SimpleNamespace(process_runner=runner)
        service = SimpleNamespace(pid=100, listener_pids=None)

        resolved = listener_pids_for_port(runtime, 8000)
        refresh_service_listener_pids(runtime, service, port=8000)

        self.assertEqual(resolved, [41, 42])
        self.assertEqual(service.listener_pids, [54, 55])

    def test_rebind_stale_service_pid_updates_service_and_emits(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runner = _RunnerStub()
        runner.wait_for_port_result = True
        runner.listener_pids_result = [222]
        runtime = SimpleNamespace(
            config=SimpleNamespace(runtime_truth_mode="auto"),
            process_runner=runner,
            _listener_truth_enforced=lambda: True,
            _service_port=lambda service: 8000,
            _service_truth_timeout=lambda: 0.5,
            _emit=lambda event, **payload: events.append((event, payload)),
        )
        service = SimpleNamespace(name="Main Backend", pid=111, listener_pids=None)

        rebound = rebind_stale_service_pid(runtime, service, previous_pid=111)

        self.assertTrue(rebound)
        self.assertEqual(service.pid, 222)
        self.assertEqual(service.listener_pids, [222])
        self.assertEqual(events[0][0], "service.rebind.pid")

    def test_service_truth_status_emits_status_event(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []

        class _Probe:
            backend = None

            @staticmethod
            def service_truth_status(**_kwargs):  # noqa: ANN003
                return "running"

        runtime = SimpleNamespace(
            process_probe=_Probe(),
            process_runner=_RunnerStub(),
            _listener_truth_enforced=lambda: True,
            _service_truth_timeout=lambda: 0.5,
            _service_within_startup_grace=lambda _service: False,
            _service_truth_discovery=lambda _service, _port: None,
            _clear_service_listener_pids=lambda _service: None,
            _refresh_service_listener_pids=lambda _service, port: None,
            _emit=lambda event, **payload: events.append((event, payload)),
            _service_truth_fallback_enabled=lambda: False,
            _rebind_stale_service_pid=lambda _service, previous_pid: False,
        )
        service = SimpleNamespace(name="Main Backend")

        status = service_truth_status(runtime, service)

        self.assertEqual(status, "running")
        self.assertEqual(events[0][0], "service.truth.check")

    def test_assert_project_services_post_start_truth_raises_with_detail(self) -> None:
        events: list[tuple[str, dict[str, object]]] = []
        runner = _RunnerStub()
        runner.running_result = False

        class _Probe:
            backend = None

            @staticmethod
            def service_truth_status(**_kwargs):  # noqa: ANN003
                return "stale"

        runtime = SimpleNamespace(
            config=SimpleNamespace(runtime_truth_mode="auto"),
            process_runner=runner,
            process_probe=_Probe(),
            _listener_truth_enforced=lambda: True,
            _service_truth_timeout=lambda: 0.5,
            _service_within_startup_grace=lambda _service: False,
            _service_truth_discovery=lambda _service, _port: None,
            _clear_service_listener_pids=lambda _service: None,
            _refresh_service_listener_pids=lambda _service, port: None,
            _service_truth_fallback_enabled=lambda: False,
            _rebind_stale_service_pid=lambda _service, previous_pid: False,
            _service_port=lambda service: 8000,
            _emit=lambda event, **payload: events.append((event, payload)),
        )
        service = SimpleNamespace(type="backend", pid=10, log_path="/tmp/x.log", status="running")
        context = SimpleNamespace(name="feature-a-1")

        with self.assertRaises(RuntimeError):
            assert_project_services_post_start_truth(runtime, context=context, services={"svc": service})

        self.assertTrue(any(event == "service.failure" for event, _payload in events))


if __name__ == "__main__":
    unittest.main()
