from __future__ import annotations

import tempfile
import unittest
import subprocess
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.shared.ports import PortPlanner


class PortsAvailabilityStrategiesTests(unittest.TestCase):
    def test_lock_only_mode_skips_host_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = PortPlanner(lock_dir=tmpdir, availability_mode="lock_only")
            self.assertTrue(planner._is_port_available(8000))

    def test_auto_mode_falls_back_to_listener_query_on_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = PortPlanner(lock_dir=tmpdir, availability_mode="auto")

            mocked_socket = MagicMock()
            mocked_socket.bind.side_effect = PermissionError("sandbox")
            socket_cm = MagicMock()
            socket_cm.__enter__.return_value = mocked_socket
            socket_cm.__exit__.return_value = None

            with patch("envctl_engine.shared.ports.socket.socket", return_value=socket_cm):
                with patch.object(planner, "_is_port_available_via_listener_query", return_value=True) as fallback:
                    self.assertTrue(planner._is_port_available(8100))
                    fallback.assert_called_once_with(8100)

    def test_socket_bind_mode_does_not_fallback_on_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = PortPlanner(lock_dir=tmpdir, availability_mode="socket_bind")

            mocked_socket = MagicMock()
            mocked_socket.bind.side_effect = PermissionError("sandbox")
            socket_cm = MagicMock()
            socket_cm.__enter__.return_value = mocked_socket
            socket_cm.__exit__.return_value = None

            with patch("envctl_engine.shared.ports.socket.socket", return_value=socket_cm):
                with patch.object(planner, "_is_port_available_via_listener_query", return_value=True) as fallback:
                    self.assertFalse(planner._is_port_available(8101))
                    fallback.assert_not_called()

    def test_socket_bind_mode_detects_bound_loopback_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = PortPlanner(lock_dir=tmpdir, availability_mode="socket_bind")
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                try:
                    listener.bind(("127.0.0.1", 0))
                except PermissionError:
                    self.skipTest("loopback bind is not permitted in this environment")
                port = listener.getsockname()[1]
                self.assertGreater(port, 0)
                self.assertFalse(planner._is_port_available(port))

    def test_auto_mode_treats_docker_hostconfig_publish_as_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = PortPlanner(lock_dir=tmpdir, availability_mode="auto")
            completed = subprocess.CompletedProcess(
                ["docker", "ps"],
                0,
                "container-id\n",
                "",
            )

            with patch.object(planner, "_is_port_available_via_socket_bind", return_value=True):
                with patch("envctl_engine.shared.ports.shutil.which", return_value="/usr/bin/docker"):
                    with patch("envctl_engine.shared.ports.subprocess.run", return_value=completed) as run:
                        self.assertFalse(planner._is_port_available(5636))

            run.assert_called_once()

    def test_docker_publish_filter_failure_does_not_block_port_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            planner = PortPlanner(lock_dir=tmpdir, availability_mode="auto")
            completed = subprocess.CompletedProcess(
                ["docker", "ps"],
                1,
                "",
                "docker unavailable",
            )

            with patch.object(planner, "_is_port_available_via_socket_bind", return_value=True):
                with patch("envctl_engine.shared.ports.shutil.which", return_value="/usr/bin/docker"):
                    with patch("envctl_engine.shared.ports.subprocess.run", return_value=completed):
                        self.assertTrue(planner._is_port_available(5637))


if __name__ == "__main__":
    unittest.main()
