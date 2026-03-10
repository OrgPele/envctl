from __future__ import annotations

import signal
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.shared.process_runner import ProcessRunner


class ProcessRunnerListenerDetectionTests(unittest.TestCase):
    def _fake_run_for_ports(self, ports_by_pid: dict[int, list[int]]):
        def _run(cmd, **kwargs):  # noqa: ANN001
            _ = kwargs
            command = list(cmd)
            if command[:3] == ["ps", "-axo", "pid=,ppid="]:
                ps_stdout = "100 1\n200 100\n"
                return subprocess.CompletedProcess(command, 0, ps_stdout, "")
            if command[:2] == ["/usr/bin/lsof", "-nP"]:
                pid = int(command[command.index("-p") + 1])
                lines: list[str] = []
                for port in ports_by_pid.get(pid, []):
                    lines.append(f"python3 {pid} user 10u IPv4 0x0 0t0 TCP 127.0.0.1:{port} (LISTEN)")
                stdout = "\n".join(lines)
                return subprocess.CompletedProcess(command, 0, stdout, "")
            return subprocess.CompletedProcess(command, 1, "", "")

        return _run

    def test_find_pid_listener_port_prefers_exact_requested_port(self) -> None:
        runner = ProcessRunner()
        with (
            patch("envctl_engine.shared.process_runner.shutil.which", return_value="/usr/bin/lsof"),
            patch(
                "envctl_engine.shared.process_runner.subprocess.run",
                side_effect=self._fake_run_for_ports({100: [9000], 200: [9004]}),
            ),
        ):
            actual = runner.find_pid_listener_port(100, 9000, max_delta=10)

        self.assertEqual(actual, 9000)

    def test_find_pid_listener_port_uses_closest_higher_port_within_delta(self) -> None:
        runner = ProcessRunner()
        with (
            patch("envctl_engine.shared.process_runner.shutil.which", return_value="/usr/bin/lsof"),
            patch(
                "envctl_engine.shared.process_runner.subprocess.run",
                side_effect=self._fake_run_for_ports({100: [], 200: [9004]}),
            ),
        ):
            actual = runner.find_pid_listener_port(100, 9000, max_delta=10)

        self.assertEqual(actual, 9004)

    def test_find_pid_listener_port_returns_none_when_outside_delta(self) -> None:
        runner = ProcessRunner()
        with (
            patch("envctl_engine.shared.process_runner.shutil.which", return_value="/usr/bin/lsof"),
            patch(
                "envctl_engine.shared.process_runner.subprocess.run",
                side_effect=self._fake_run_for_ports({100: [], 200: [9800]}),
            ),
        ):
            actual = runner.find_pid_listener_port(100, 9000, max_delta=25)

        self.assertIsNone(actual)

    def test_wait_for_pid_port_accepts_process_tree_listener(self) -> None:
        runner = ProcessRunner()
        with (
            patch.object(runner, "is_pid_running", return_value=True),
            patch.object(runner, "pid_owns_port", return_value=False),
            patch.object(runner, "find_pid_listener_port", return_value=9000),
        ):
            self.assertTrue(runner.wait_for_pid_port(100, 9000, timeout=0.1))

    def test_wait_for_pid_port_does_not_accept_unrelated_listener(self) -> None:
        runner = ProcessRunner()
        with (
            patch.object(runner, "is_pid_running", side_effect=[True, False]),
            patch.object(runner, "pid_owns_port", return_value=False),
            patch.object(runner, "find_pid_listener_port", return_value=None),
            patch.object(runner, "wait_for_port", side_effect=AssertionError("wait_for_port should not be used")),
            patch("envctl_engine.shared.process_runner.time.sleep", return_value=None),
        ):
            self.assertFalse(runner.wait_for_pid_port(100, 9000, timeout=0.1))

    def test_pid_owns_port_does_not_fallback_to_generic_listener_when_lsof_missing(self) -> None:
        runner = ProcessRunner()
        with (
            patch("envctl_engine.shared.process_runner.shutil.which", return_value=None),
            patch.object(runner, "wait_for_port", side_effect=AssertionError("wait_for_port should not be used")),
        ):
            self.assertFalse(runner.pid_owns_port(100, 9000))

    def test_pid_owns_port_handles_permission_error_from_lsof(self) -> None:
        runner = ProcessRunner()
        with (
            patch("envctl_engine.shared.process_runner.shutil.which", return_value="/usr/bin/lsof"),
            patch("envctl_engine.shared.process_runner.subprocess.run", side_effect=PermissionError("blocked")),
        ):
            self.assertFalse(runner.pid_owns_port(100, 9000))

    def test_find_pid_listener_port_handles_permission_error_from_ps(self) -> None:
        runner = ProcessRunner()
        with (
            patch("envctl_engine.shared.process_runner.shutil.which", return_value="/usr/bin/lsof"),
            patch("envctl_engine.shared.process_runner.subprocess.run", side_effect=PermissionError("blocked")),
        ):
            self.assertIsNone(runner.find_pid_listener_port(100, 9000, max_delta=10))

    def test_wait_for_port_accepts_ipv6_loopback_when_ipv4_refused(self) -> None:
        runner = ProcessRunner()

        class _FakeSocket:
            def __init__(self, family: int, *_args: object) -> None:
                self.family = family

            def __enter__(self) -> "_FakeSocket":
                return self

            def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
                _ = exc_type, exc, tb
                return False

            def settimeout(self, _timeout: float) -> None:
                return None

            def connect_ex(self, _address: object) -> int:
                if self.family == socket.AF_INET6:
                    return 0
                return 1

        import socket

        with (
            patch(
                "envctl_engine.shared.process_runner.socket.getaddrinfo",
                return_value=[
                    (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 9000)),
                    (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("::1", 9000, 0, 0)),
                ],
            ),
            patch(
                "envctl_engine.shared.process_runner.socket.socket", side_effect=lambda family, *_a: _FakeSocket(family)
            ),
            patch("envctl_engine.shared.process_runner.time.monotonic", side_effect=[0.0, 0.0, 0.2]),
            patch("envctl_engine.shared.process_runner.time.sleep", return_value=None),
        ):
            self.assertTrue(runner.wait_for_port(9000, host="127.0.0.1", timeout=0.1))

    def test_run_returns_controlled_timeout_result_instead_of_raising(self) -> None:
        runner = ProcessRunner()

        class _FakeProcess:
            pid = 4321

            def communicate(self, timeout=None):  # noqa: ANN001
                raise subprocess.TimeoutExpired(cmd=["docker", "run"], timeout=120.0)

        with (
            patch("envctl_engine.shared.process_runner.subprocess.Popen", return_value=_FakeProcess()),
            patch("envctl_engine.shared.process_runner.os.killpg"),
        ):
            result = runner.run(["docker", "run"], timeout=120.0)

        self.assertEqual(result.returncode, 124)
        self.assertIn("Command timed out after 120.0s: docker run", result.stderr)

    def test_run_timeout_preserves_partial_stdout_and_stderr(self) -> None:
        runner = ProcessRunner()

        class _FakeProcess:
            pid = 4321

            def __init__(self) -> None:
                self.calls = 0

            def communicate(self, timeout=None):  # noqa: ANN001
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired(
                        cmd=["docker", "run"],
                        timeout=30.0,
                        output="partial stdout",
                        stderr="partial stderr",
                    )
                return ("tail stdout", "tail stderr")

        with (
            patch("envctl_engine.shared.process_runner.subprocess.Popen", return_value=_FakeProcess()),
            patch("envctl_engine.shared.process_runner.os.killpg"),
        ):
            result = runner.run(["docker", "run"], timeout=30.0)

        self.assertEqual(result.returncode, 124)
        self.assertIn("partial stderr", result.stderr)
        self.assertIn("tail stderr", result.stderr)
        self.assertIn("Command timed out after 30.0s: docker run", result.stderr)
        self.assertEqual(result.stdout, "partial stdouttail stdout")

    def test_run_timeout_kills_process_group(self) -> None:
        runner = ProcessRunner()

        class _FakeProcess:
            pid = 9876

            def communicate(self, timeout=None):  # noqa: ANN001
                raise subprocess.TimeoutExpired(cmd=["docker", "run"], timeout=5.0)

        with (
            patch("envctl_engine.shared.process_runner.subprocess.Popen", return_value=_FakeProcess()),
            patch("envctl_engine.shared.process_runner.os.killpg") as killpg,
        ):
            result = runner.run(["docker", "run"], timeout=5.0)

        self.assertEqual(result.returncode, 124)
        killpg.assert_any_call(9876, signal.SIGTERM)

    def test_terminate_avoids_sigkill_when_pid_identity_changes_after_sigterm(self) -> None:
        runner = ProcessRunner()
        kill_calls: list[tuple[int, int]] = []

        def _fake_kill(pid: int, sig: int) -> None:
            kill_calls.append((pid, sig))

        with (
            patch("envctl_engine.shared.process_runner.os.kill", side_effect=_fake_kill),
            patch.object(runner, "is_pid_running", return_value=True),
            patch.object(runner, "_pid_identity", side_effect=["orig", "reused"], create=True),
            patch(
                "envctl_engine.shared.process_runner.time.monotonic",
                side_effect=[0.0, 0.0, 0.2, 0.2, 0.2, 0.4],
            ),
            patch("envctl_engine.shared.process_runner.time.sleep", return_value=None),
        ):
            result = runner.terminate(4321, term_timeout=0.1, kill_timeout=0.1)

        self.assertTrue(result)
        self.assertEqual(kill_calls, [(4321, signal.SIGTERM)])

    def test_terminate_sends_sigkill_when_pid_identity_is_stable(self) -> None:
        runner = ProcessRunner()
        kill_calls: list[tuple[int, int]] = []

        def _fake_kill(pid: int, sig: int) -> None:
            kill_calls.append((pid, sig))

        with (
            patch("envctl_engine.shared.process_runner.os.kill", side_effect=_fake_kill),
            patch.object(runner, "is_pid_running", side_effect=[True, True, False]),
            patch.object(runner, "_pid_identity", side_effect=["orig"] * 8, create=True),
            patch(
                "envctl_engine.shared.process_runner.time.monotonic",
                side_effect=[0.0, 0.0, 0.2, 0.2, 0.2, 0.4],
            ),
            patch("envctl_engine.shared.process_runner.time.sleep", return_value=None),
        ):
            result = runner.terminate(5678, term_timeout=0.1, kill_timeout=0.1)

        self.assertTrue(result)
        self.assertEqual(kill_calls, [(5678, signal.SIGTERM), (5678, signal.SIGKILL)])


if __name__ == "__main__":
    unittest.main()
