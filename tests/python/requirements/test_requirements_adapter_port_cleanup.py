from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
import unittest

from envctl_engine.requirements.adapter_port_cleanup import (
    bind_safe_cleanup_enabled,
    cleanup_envctl_owned_port_containers,
    format_bind_conflict_guidance,
    wait_for_port_ready,
)


class RequirementsAdapterPortCleanupTests(unittest.TestCase):
    def test_bind_safe_cleanup_honors_global_and_service_overrides(self) -> None:
        self.assertFalse(bind_safe_cleanup_enabled({}, service_name="postgres"))
        self.assertTrue(
            bind_safe_cleanup_enabled({"ENVCTL_REQUIREMENT_BIND_SAFE_CLEANUP": "true"}, service_name="postgres")
        )
        self.assertFalse(
            bind_safe_cleanup_enabled(
                {
                    "ENVCTL_REQUIREMENT_BIND_SAFE_CLEANUP": "true",
                    "ENVCTL_REQUIREMENT_POSTGRES_BIND_SAFE_CLEANUP": "false",
                },
                service_name="postgres",
            )
        )

    def test_cleanup_envctl_owned_port_containers_removes_only_allowed_prefixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _DockerRunner(
                subprocess.CompletedProcess(
                    args=["docker"],
                    returncode=0,
                    stdout="envctl-postgres-a\nforeign-db\nenvctl-redis-b\n",
                    stderr="",
                )
            )

            cleaned, error = cleanup_envctl_owned_port_containers(
                process_runner=runner,
                project_root=Path(tmpdir),
                env={},
                port=5432,
                allowed_prefixes=("envctl-postgres-",),
            )

        self.assertTrue(cleaned)
        self.assertIsNone(error)
        self.assertEqual(runner.commands[0][1:3], ["ps", "-a"])
        self.assertIn(["docker", "rm", "-f", "envctl-postgres-a"], runner.commands)
        self.assertNotIn(["docker", "rm", "-f", "foreign-db"], runner.commands)
        self.assertNotIn(["docker", "rm", "-f", "envctl-redis-b"], runner.commands)

    def test_format_bind_conflict_guidance_includes_manual_and_safe_cleanup_hint(self) -> None:
        message = format_bind_conflict_guidance("postgres", 5432, "bind conflict")
        self.assertIn("Unable to acquire port 5432 for postgres", message)
        self.assertIn("ENVCTL_REQUIREMENT_BIND_SAFE_CLEANUP=true", message)

    def test_wait_for_port_ready_uses_runner_waiter_variants(self) -> None:
        self.assertTrue(wait_for_port_ready(_WaitRunner(lambda port, *, timeout: port == 5432 and timeout == 1.0), 5432, timeout=1.0))
        self.assertTrue(wait_for_port_ready(_WaitRunner(lambda port: port == 5432), 5432, timeout=1.0))
        self.assertFalse(wait_for_port_ready(object(), 5432, timeout=1.0))


class _DockerRunner:
    def __init__(self, list_result: subprocess.CompletedProcess[str]) -> None:
        self.list_result = list_result
        self.commands: list[list[str]] = []

    def run(self, command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        if command[:3] == ["docker", "ps", "-a"]:
            return self.list_result
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")


class _WaitRunner:
    def __init__(self, waiter: object) -> None:
        self.wait_for_port = waiter


if __name__ == "__main__":
    unittest.main()
