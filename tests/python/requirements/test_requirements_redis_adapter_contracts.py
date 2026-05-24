# ruff: noqa: F403,F405
from __future__ import annotations

import unittest

from tests.python.requirements.requirements_adapter_contract_support import *


class RedisAdapterContractTests(unittest.TestCase):
    def test_redis_pulls_image_before_create_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={},
            )

            self.assertTrue(result.success)
            pull_index = next(i for i, cmd in enumerate(runner.commands) if cmd[:2] == ["docker", "pull"])
            create_index = next(i for i, cmd in enumerate(runner.commands) if cmd[:2] == ["docker", "create"])
            self.assertLess(pull_index, create_index)

    def test_redis_skips_default_pull_when_image_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            runner.images.add("redis:7-alpine")

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={},
            )

            self.assertTrue(result.success)
            self.assertTrue(any(cmd[:3] == ["docker", "image", "inspect"] for cmd in runner.commands))
            self.assertFalse(any(cmd[:2] == ["docker", "pull"] for cmd in runner.commands))

    def test_redis_adopts_existing_port_mapping_without_recreate_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="Main",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "exited"
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6399\n"

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 6399)
            self.assertTrue(result.port_adopted)
            self.assertTrue(result.container_reused)
            self.assertFalse(result.container_recreated)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container_name for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            create_seen = any(
                cmd[:2] == ["docker", "create"] and "--name" in cmd and container_name in cmd for cmd in runner.commands
            )
            start_seen = any(cmd[:2] == ["docker", "start"] and cmd[-1] == container_name for cmd in runner.commands)
            self.assertFalse(stop_seen)
            self.assertFalse(rm_seen)
            self.assertFalse(create_seen)
            self.assertTrue(start_seen)

    def test_redis_recreates_on_port_mismatch_when_policy_is_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="Main",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "exited"
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6399\n"

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={"ENVCTL_REQUIREMENTS_PORT_MISMATCH_POLICY": "recreate"},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 6380)
            self.assertFalse(result.port_adopted)
            self.assertFalse(result.container_reused)
            self.assertTrue(result.container_recreated)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container_name for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            create_seen = any(
                cmd[:2] == ["docker", "create"] and "--name" in cmd and container_name in cmd for cmd in runner.commands
            )
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)
            self.assertTrue(create_seen)

    def test_redis_adopted_existing_uses_settle_probe_without_restart_or_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="Main",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "running"
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6399\n"
            runner.exec_returncode_sequence[container_name] = [1, 0]
            runner.exec_stderr_sequence[container_name] = ["loading", ""]

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={"ENVCTL_REDIS_PROBE_ATTEMPTS": "1", "ENVCTL_REDIS_RESTART_PROBE_ATTEMPTS": "2"},
            )

            self.assertTrue(result.success)
            self.assertTrue(result.port_adopted)
            self.assertFalse(
                any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            )

    def test_redis_recreates_adopted_container_when_host_listener_never_appears(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="Main",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "running"
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6399\n"
            runner.wait_for_port_sequences[6399] = [False, False, False]
            runner.wait_for_port_sequences[6380] = [True]

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={
                    "ENVCTL_REDIS_PROBE_ATTEMPTS": "1",
                    "ENVCTL_REDIS_RESTART_PROBE_ATTEMPTS": "1",
                    "ENVCTL_REDIS_RECREATE_PROBE_ATTEMPTS": "1",
                },
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 6380)
            self.assertFalse(result.port_adopted)
            self.assertTrue(result.container_recreated)
            self.assertTrue(
                any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertTrue(
                any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "create"] and "--name" in cmd and container_name in cmd
                    for cmd in runner.commands
                )
            )

    def test_redis_recovers_when_create_times_out_but_container_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="Main",
            )
            runner.create_timeout.add(container_name)
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6380\n"

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 6380)
            self.assertFalse(result.container_recreated)

    def test_redis_recovers_when_docker_start_reports_failure_but_container_is_running(self) -> None:
        class _Runner(_FakeRunner):
            def run(self, cmd, *, cwd=None, env=None, timeout=None, process_started_callback=None):  # noqa: ANN001
                command = list(cmd)
                if command[:2] == ["docker", "start"]:
                    container = command[2]
                    self.commands.append(command)
                    self.existing.add(container)
                    self.status[container] = "running"
                    return subprocess.CompletedProcess(command, 1, "", "")
                return super().run(
                    cmd,
                    cwd=cwd,
                    env=env,
                    timeout=timeout,
                    process_started_callback=process_started_callback,
                )

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _Runner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="Main",
            )
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6380\n"

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 6380)

    def test_redis_recovered_create_uses_settle_probe_without_restart_or_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="Main",
            )
            runner.create_timeout.add(container_name)
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6380\n"
            runner.exec_returncode_sequence[container_name] = [1, 0]
            runner.exec_stderr_sequence[container_name] = ["loading", ""]

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=6380,
                env={"ENVCTL_REDIS_PROBE_ATTEMPTS": "1", "ENVCTL_REDIS_RESTART_PROBE_ATTEMPTS": "2"},
            )

            self.assertTrue(result.success)
            self.assertFalse(
                any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            )

    def test_redis_created_bind_conflict_container_is_cleaned_in_discover(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-redis",
                project_root=root,
                project_name="feature-a-1",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "created"
            runner.port_mappings[(container_name, "6379")] = "0.0.0.0:6384\n"
            runner.state_error[container_name] = "Bind for 0.0.0.0:6384 failed: port is already allocated"

            result = start_redis_container(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                port=6384,
            )

            self.assertTrue(result.success)
            self.assertIn(["docker", "stop", container_name], runner.commands)
            self.assertIn(["docker", "rm", "-f", container_name], runner.commands)
            self.assertIn(
                ["docker", "create", "--name", container_name, "-p", "6384:6379", "redis:7-alpine"], runner.commands
            )

    def test_redis_fails_when_ping_probe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_first.success)

            container = result_first.container_name
            runner.exec_returncode[container] = 1
            runner.exec_stderr[container] = "NOAUTH"

            result_second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertFalse(result_second.success)
            self.assertIn("redis-cli ping", result_second.error or "")

    def test_redis_retries_ping_probe_before_declaring_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_first.success)

            container = result_first.container_name
            runner.exec_returncode_sequence[container] = [1, 0]
            runner.exec_stderr_sequence[container] = ["LOADING", ""]

            result_second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_second.success)
            exec_calls = [cmd for cmd in runner.commands if cmd[:2] == ["docker", "exec"] and cmd[2] == container]
            self.assertGreaterEqual(len(exec_calls), 3)
            self.assertGreaterEqual(len(runner.sleep_calls), 1)

    def test_redis_ping_probe_uses_backoff_before_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_first.success)

            container = result_first.container_name
            runner.exec_returncode[container] = 1
            runner.exec_stderr[container] = "NOAUTH"

            result_second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertFalse(result_second.success)
            self.assertIn("redis-cli ping", result_second.error or "")
            self.assertGreaterEqual(len(runner.sleep_calls), 3)

    def test_redis_restarts_once_after_probe_exhaustion_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_first.success)

            container = result_first.container_name
            runner.port_mappings[(container, "6379")] = "0.0.0.0:6380"
            runner.exec_returncode_sequence[container] = [1] * 20 + [0]
            runner.exec_stderr_sequence[container] = ["LOADING"] * 20 + [""]

            result_second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)

    def test_redis_restarts_when_listener_timeout_occurs_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "6379")] = "0.0.0.0:6380"
            runner.wait_for_port_sequences[6380] = [False, True]

            second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)

    def test_redis_listener_wait_timeout_honors_env_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
                env={"ENVCTL_REDIS_LISTENER_WAIT_TIMEOUT_SECONDS": "33"},
            )
            self.assertTrue(result.success)
            self.assertTrue(any(port == 6380 and timeout == 33.0 for port, timeout in runner.wait_for_port_calls))

    def test_redis_recreates_after_restart_listener_timeout_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "6379")] = "0.0.0.0:6380"
            runner.wait_for_port_sequences[6380] = [False, False, True]

            second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_redis_recreates_after_restart_probe_exhaustion_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_first.success)

            container = result_first.container_name
            runner.port_mappings[(container, "6379")] = "0.0.0.0:6380"
            runner.exec_returncode_sequence[container] = [1] * 50 + [0]
            runner.exec_stderr_sequence[container] = ["LOADING"] * 50 + [""]

            result_second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_redis_reports_recreate_failure_when_recreate_run_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(result_first.success)

            container = result_first.container_name
            runner.port_mappings[(container, "6379")] = "0.0.0.0:6380"
            runner.exec_returncode[container] = 1
            runner.exec_stderr[container] = "LOADING"
            runner.create_returncode[container] = 1
            runner.create_stderr[container] = "create failed"

            result_second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertFalse(result_second.success)
            self.assertIn("failed recreating redis container", result_second.error or "")

    def test_redis_recreates_existing_container_when_mapping_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "6379")] = ""

            second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(second.success)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_redis_recreates_existing_container_when_port_command_reports_no_public_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mapping_errors[(container, "6379")] = "Error: No public port '6379' published for envctl-redis"

            second = start_redis_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=6380,
            )
            self.assertTrue(second.success)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)


if __name__ == "__main__":
    unittest.main()
