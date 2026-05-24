# ruff: noqa: F403,F405
from __future__ import annotations

import unittest

from tests.python.requirements.requirements_adapter_contract_support import *


class N8nAdapterContractTests(unittest.TestCase):
    def test_n8n_recovers_when_recreate_times_out_but_container_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-n8n",
                project_root=root,
                project_name="Main",
            )
            runner.create_timeout.add(container_name)
            runner.port_mappings[(container_name, "5678")] = "0.0.0.0:5680\n"
            runner.wait_for_port_sequences[5680] = [False, False, True]

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 5680)

    def test_n8n_recovers_when_docker_start_reports_failure_but_container_is_running(self) -> None:
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
                prefix="envctl-n8n",
                project_root=root,
                project_name="Main",
            )
            runner.port_mappings[(container_name, "5678")] = "0.0.0.0:5680\n"

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 5680)

    def test_n8n_uses_configured_image_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={"ENVCTL_N8N_IMAGE": "n8nio/n8n:1.0.0"},
            )

            self.assertTrue(result.success)
            create_commands = [cmd for cmd in runner.commands if cmd[:2] == ["docker", "create"]]
            self.assertTrue(create_commands)
            self.assertEqual(create_commands[0][-1], "n8nio/n8n:1.0.0")

    def test_n8n_pulls_image_before_create_by_default_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={},
            )

            self.assertTrue(result.success)
            pull_index = next(i for i, cmd in enumerate(runner.commands) if cmd[:2] == ["docker", "pull"])
            create_index = next(i for i, cmd in enumerate(runner.commands) if cmd[:2] == ["docker", "create"])
            self.assertLess(pull_index, create_index)

    def test_n8n_skips_default_pull_when_image_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            runner.images.add("n8nio/n8n:latest")

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={},
            )

            self.assertTrue(result.success)
            self.assertTrue(any(cmd[:3] == ["docker", "image", "inspect"] for cmd in runner.commands))
            self.assertFalse(any(cmd[:2] == ["docker", "pull"] for cmd in runner.commands))

    def test_n8n_legacy_pull_flag_forces_pull_when_image_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            runner.images.add("n8nio/n8n:latest")

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={"ENVCTL_N8N_PULL_IMAGE": "true"},
            )

            self.assertTrue(result.success)
            pull_index = next(i for i, cmd in enumerate(runner.commands) if cmd[:2] == ["docker", "pull"])
            create_index = next(i for i, cmd in enumerate(runner.commands) if cmd[:2] == ["docker", "create"])
            self.assertLess(pull_index, create_index)

    def test_n8n_can_skip_image_pull(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={"ENVCTL_N8N_PULL_IMAGE": "false"},
            )

            self.assertTrue(result.success)
            self.assertFalse(any(cmd[:2] == ["docker", "pull"] for cmd in runner.commands))

    def test_n8n_adopted_existing_uses_settle_listener_without_restart_or_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-n8n",
                project_root=root,
                project_name="Main",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "running"
            runner.port_mappings[(container_name, "5678")] = "0.0.0.0:5681\n"
            runner.wait_for_port_sequences[5681] = [False, True]

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={},
            )

            self.assertTrue(result.success)
            self.assertTrue(result.port_adopted)
            self.assertEqual(result.effective_port, 5681)
            self.assertFalse(
                any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            )

    def test_n8n_recovered_create_uses_settle_listener_without_restart_or_recreate(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-n8n",
                project_root=root,
                project_name="Main",
            )
            runner.create_timeout.add(container_name)
            runner.port_mappings[(container_name, "5678")] = "0.0.0.0:5680\n"
            runner.wait_for_port_sequences[5680] = [False, True]

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                port=5680,
                env={},
            )

            self.assertTrue(result.success)
            self.assertFalse(
                any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container_name for cmd in runner.commands)
            )
            self.assertFalse(
                any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            )

    def test_n8n_created_bind_conflict_container_is_cleaned_in_discover(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_container_name(
                prefix="envctl-n8n",
                project_root=root,
                project_name="feature-a-1",
            )
            runner.existing.add(container_name)
            runner.status[container_name] = "created"
            runner.port_mappings[(container_name, "5678")] = "0.0.0.0:5683\n"
            runner.state_error[container_name] = "Bind for 0.0.0.0:5683 failed: port is already allocated"
            runner.wait_for_port_overrides[5683] = True

            result = start_n8n_container(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                port=5683,
            )

            self.assertTrue(result.success)
            self.assertIn(["docker", "stop", container_name], runner.commands)
            self.assertIn(["docker", "rm", "-f", container_name], runner.commands)

    def test_n8n_adopts_existing_container_port_mapping_on_mismatch_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result_first = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(result_first.success)
            container = result_first.container_name
            runner.port_mappings[(container, "5678")] = "0.0.0.0:5688\n"
            runner.status[container] = "exited"

            result_second = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5679,
            )
            self.assertTrue(result_second.success)
            self.assertEqual(result_second.effective_port, 5688)
            self.assertTrue(result_second.port_adopted)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            recreate_seen = any(cmd[:2] == ["docker", "create"] and "5679:5678" in cmd for cmd in runner.commands)
            start_seen = any(cmd[:2] == ["docker", "start"] and cmd[-1] == container for cmd in runner.commands)
            self.assertFalse(stop_seen)
            self.assertFalse(rm_seen)
            self.assertFalse(recreate_seen)
            self.assertTrue(start_seen)

    def test_n8n_recreates_existing_container_when_mapping_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5678")] = ""

            second = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(second.success)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_n8n_recreates_existing_container_when_port_command_reports_no_public_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mapping_errors[(container, "5678")] = "Error: No public port '5678' published for envctl-n8n"

            second = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(second.success)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_n8n_restarts_when_port_probe_times_out_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5678")] = "0.0.0.0:5678"
            runner.wait_for_port_sequences[5678] = [False, True]

            second = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)

    def test_n8n_recreates_after_restart_probe_timeout_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5678")] = "0.0.0.0:5678"
            runner.wait_for_port_sequences[5678] = [False, False, True]

            second = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(second.success)
            restart_seen = any(cmd[:2] == ["docker", "restart"] and cmd[-1] == container for cmd in runner.commands)
            stop_seen = any(cmd[:2] == ["docker", "stop"] and cmd[-1] == container for cmd in runner.commands)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container for cmd in runner.commands)
            self.assertTrue(restart_seen)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_n8n_uses_reduced_default_probe_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(result.success)
            self.assertTrue(any(port == 5678 and timeout == 6.0 for port, timeout in runner.wait_for_port_calls))

    def test_n8n_reports_recreate_failure_when_recreate_run_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            first = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertTrue(first.success)
            container = first.container_name
            runner.port_mappings[(container, "5678")] = "0.0.0.0:5678"
            runner.wait_for_port_sequences[5678] = [False, False]
            runner.create_returncode[container] = 1
            runner.create_stderr[container] = "create failed"

            second = start_n8n_container(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                port=5678,
            )
            self.assertFalse(second.success)
            self.assertIn("failed recreating n8n container", second.error or "")


if __name__ == "__main__":
    unittest.main()
