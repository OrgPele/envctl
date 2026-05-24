# ruff: noqa: F403,F405
from __future__ import annotations

import unittest

from tests.python.requirements.requirements_adapter_contract_support import *


class PostgresAdapterContractTests(unittest.TestCase):
    def test_postgres_pulls_image_before_run_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()

            result = start_postgres_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
                env={},
            )

            self.assertTrue(result.success)
            pull_index = next(i for i, cmd in enumerate(runner.commands) if cmd[:2] == ["docker", "pull"])
            run_index = next(i for i, cmd in enumerate(runner.commands) if cmd[:2] == ["docker", "run"])
            self.assertLess(pull_index, run_index)

    def test_postgres_skips_default_pull_when_image_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            runner.images.add("postgres:15-alpine")

            result = start_postgres_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
                env={},
            )

            self.assertTrue(result.success)
            self.assertTrue(any(cmd[:3] == ["docker", "image", "inspect"] for cmd in runner.commands))
            self.assertFalse(any(cmd[:2] == ["docker", "pull"] for cmd in runner.commands))

    def test_postgres_creates_container_and_probes_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(result.success)
            self.assertIn("envctl-postgres", result.container_name)
            self.assertTrue(any(cmd[:2] == ["docker", "run"] for cmd in runner.commands))
            self.assertTrue(any("5434:5432" in cmd for cmd in runner.commands))
            self.assertTrue(any(cmd[:2] == ["docker", "exec"] for cmd in runner.commands))

    def test_postgres_retries_readiness_probe_before_declaring_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name

            runner.exec_returncode_sequence[container] = [2, 0]
            runner.exec_stderr_sequence[container] = ["/var/run/postgresql:5432 - no response", ""]

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertTrue(result.success)
            exec_calls = [cmd for cmd in runner.commands if cmd[:2] == ["docker", "exec"] and cmd[2] == container]
            self.assertGreaterEqual(len(exec_calls), 3)
            self.assertGreaterEqual(len(runner.sleep_calls), 1)

    def test_postgres_readiness_probe_uses_backoff_before_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name

            runner.exec_returncode[container] = 2
            runner.exec_stderr[container] = "/var/run/postgresql:5432 - no response"

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertFalse(result.success)
            self.assertIn("no response", result.error or "")
            self.assertGreaterEqual(len(runner.sleep_calls), 3)

    def test_postgres_slow_probe_eventually_succeeds_after_many_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name

            runner.exec_returncode_sequence[container] = [2] * 25 + [0]
            runner.exec_stderr_sequence[container] = ["/var/run/postgresql:5432 - no response"] * 25 + [""]

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertTrue(result.success)

    def test_postgres_restarts_once_after_probe_exhaustion_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name

            runner.exec_returncode_sequence[container] = [2] * 60 + [0]
            runner.exec_stderr_sequence[container] = ["/var/run/postgresql:5432 - no response"] * 60 + [""]

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertTrue(result.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)

    def test_postgres_restarts_when_listener_timeout_occurs_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5432")] = "0.0.0.0:5434"
            runner.wait_for_port_sequences[5434] = [False, True]

            second = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)

    def test_postgres_listener_wait_timeout_honors_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
                env={"ENVCTL_POSTGRES_LISTENER_WAIT_TIMEOUT_SECONDS": "41.5"},
            )
            self.assertTrue(result.success)
            self.assertTrue(any(port == 5434 and timeout == 41.5 for port, timeout in runner.wait_for_port_calls))

    def test_postgres_recreates_after_restart_listener_timeout_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5432")] = "0.0.0.0:5434"
            runner.wait_for_port_sequences[5434] = [False, False, True]

            second = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_postgres_reports_restart_failure_when_recovery_restart_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name

            runner.exec_returncode[container] = 2
            runner.exec_stderr[container] = "/var/run/postgresql:5432 - no response"
            runner.restart_returncode[container] = 1
            runner.restart_stderr[container] = "restart failed"

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertFalse(result.success)
            self.assertIn("failed restarting postgres container", result.error or "")

    def test_postgres_recreates_after_restart_probe_exhaustion_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name
            runner.port_mappings[(container, "5432")] = "0.0.0.0:5434"

            runner.exec_returncode_sequence[container] = [2] * 90 + [0]
            runner.exec_stderr_sequence[container] = ["/var/run/postgresql:5432 - no response"] * 90 + [""]

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertTrue(result.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_postgres_reports_recreate_failure_when_recreate_run_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            preview = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(preview.success)
            container = preview.container_name
            runner.port_mappings[(container, "5432")] = "0.0.0.0:5434"

            runner.exec_returncode[container] = 2
            runner.exec_stderr[container] = "/var/run/postgresql:5432 - no response"
            runner.run_returncode_sequence[container] = [1]
            runner.run_stderr[container] = "create failed"

            result = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )

            self.assertFalse(result.success)
            self.assertIn("failed recreating postgres container", result.error or "")

    def test_postgres_recreates_existing_container_when_mapping_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5432")] = ""

            second = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(second.success)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_postgres_recreates_existing_container_when_port_command_reports_no_public_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mapping_errors[(container, "5432")] = (
                "Error: No public port '5432' published for envctl-postgres"
            )

            second = start_postgres_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5434,
                db_user="postgres",
                db_password="postgres",
                db_name="postgres",
            )
            self.assertTrue(second.success)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)


if __name__ == "__main__":
    unittest.main()
