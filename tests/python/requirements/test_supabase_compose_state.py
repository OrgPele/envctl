from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from envctl_engine.requirements.supabase import (
    _compose_service_state,
    _compose_service_states,
    _compose_services_ready_for_handoff,
    _compose_timeout_recovered,
)


class _ComposeStateRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.compose_json_stdout: dict[str, str] = {}
        self.compose_json_returncode: dict[str, int] = {}
        self.compose_json_stderr: dict[str, str] = {}
        self.compose_ps_q_stdout: dict[str, str] = {}
        self.compose_ps_q_returncode: dict[str, int] = {}
        self.inspect_state_stdout: dict[str, str] = {}
        self.inspect_returncode: dict[str, int] = {}
        self.inspect_stderr: dict[str, str] = {}
        self.wait_for_port_calls: list[tuple[int, float]] = []
        self.wait_for_port_result = False

    def run(self, cmd, *, cwd=None, env=None, timeout=None, process_started_callback=None):  # noqa: ANN001
        _ = cwd, env, timeout, process_started_callback
        command = list(cmd)
        self.commands.append(command)
        if command[:2] == ["docker", "compose"] and "-f" in command:
            compose_args = command[command.index("-f") + 2 :]
            if compose_args[:3] == ["ps", "--format", "json"]:
                service = compose_args[3] if len(compose_args) > 3 else ""
                rc = self.compose_json_returncode.get(service, 0)
                stderr = self.compose_json_stderr.get(service, "")
                stdout = self.compose_json_stdout.get(service, "")
                return subprocess.CompletedProcess(command, rc, stdout if rc == 0 else "", stderr)
            if compose_args[:2] == ["ps", "-q"]:
                service = compose_args[2] if len(compose_args) > 2 else ""
                rc = self.compose_ps_q_returncode.get(service, 0)
                stdout = self.compose_ps_q_stdout.get(service, "")
                return subprocess.CompletedProcess(command, rc, stdout if rc == 0 else "", "compose ps failed")
        if command[:3] == ["docker", "inspect", "-f"]:
            container = command[-1]
            rc = self.inspect_returncode.get(container, 0)
            stderr = self.inspect_stderr.get(container, "")
            stdout = self.inspect_state_stdout.get(container, "")
            return subprocess.CompletedProcess(command, rc, stdout if rc == 0 else "", stderr)
        return subprocess.CompletedProcess(command, 0, "", "")

    def wait_for_port(self, port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
        _ = host
        self.wait_for_port_calls.append((port, float(timeout)))
        return self.wait_for_port_result


class SupabaseComposeStateTests(unittest.TestCase):
    def test_compose_json_classifies_service_states(self) -> None:
        runner = _ComposeStateRunner()
        runner.compose_json_stdout["supabase-db"] = json.dumps(
            [
                {
                    "Service": "supabase-db",
                    "ID": "db123",
                    "State": "running",
                    "Health": "healthy",
                    "ExitCode": 0,
                    "Publishers": [{"URL": "0.0.0.0", "PublishedPort": 5432, "TargetPort": 5432}],
                }
            ]
        )
        runner.compose_json_stdout["supabase-auth"] = json.dumps(
            [{"Service": "supabase-auth", "ID": "auth123", "State": "created"}]
        )
        runner.compose_json_stdout["supabase-kong"] = json.dumps(
            [{"Service": "supabase-kong", "ID": "kong123", "State": "exited", "ExitCode": 1}]
        )

        db_state = _compose_service_state(
            process_runner=runner,
            compose_root=Path("/tmp/supabase"),
            compose_project_name="envctl-supabase-test",
            compose_path=Path("/tmp/supabase/docker-compose.yml"),
            env={},
            service_name="supabase-db",
        )
        created_state = _compose_service_state(
            process_runner=runner,
            compose_root=Path("/tmp/supabase"),
            compose_project_name="envctl-supabase-test",
            compose_path=Path("/tmp/supabase/docker-compose.yml"),
            env={},
            service_name="supabase-auth",
        )
        exited_state = _compose_service_state(
            process_runner=runner,
            compose_root=Path("/tmp/supabase"),
            compose_project_name="envctl-supabase-test",
            compose_path=Path("/tmp/supabase/docker-compose.yml"),
            env={},
            service_name="supabase-kong",
        )

        self.assertTrue(db_state.exists)
        self.assertTrue(db_state.is_running)
        self.assertTrue(db_state.is_healthy)
        self.assertEqual(db_state.published_ports, ["0.0.0.0:5432->5432"])
        self.assertTrue(created_state.is_created)
        self.assertFalse(created_state.is_running)
        self.assertTrue(exited_state.is_terminal_failure)
        self.assertEqual(exited_state.exit_code, "1")

    def test_missing_unhealthy_and_inspect_error_states_are_explicit(self) -> None:
        runner = _ComposeStateRunner()
        runner.compose_json_stdout["missing"] = "[]"
        runner.compose_json_stdout["unhealthy"] = json.dumps(
            [{"Service": "unhealthy", "ID": "bad123", "State": "running", "Health": "unhealthy"}]
        )
        runner.compose_json_returncode["inspect-error"] = 1
        runner.compose_ps_q_stdout["inspect-error"] = "broken123\n"
        runner.inspect_returncode["broken123"] = 1
        runner.inspect_stderr["broken123"] = "inspect failed"

        missing, unhealthy, inspect_error = _compose_service_states(
            process_runner=runner,
            compose_root=Path("/tmp/supabase"),
            compose_project_name="envctl-supabase-test",
            compose_path=Path("/tmp/supabase/docker-compose.yml"),
            env={},
            service_names=["missing", "unhealthy", "inspect-error"],
        )

        self.assertFalse(missing.exists)
        self.assertEqual(missing.status, "missing")
        self.assertTrue(unhealthy.is_running)
        self.assertFalse(unhealthy.is_healthy)
        self.assertEqual(unhealthy.health, "unhealthy")
        self.assertTrue(inspect_error.exists)
        self.assertEqual(inspect_error.container_id, "broken123")
        self.assertIn("inspect failed", inspect_error.error or "")

    def test_fallback_uses_ps_q_and_docker_inspect_when_compose_json_unavailable(self) -> None:
        runner = _ComposeStateRunner()
        runner.compose_json_returncode["supabase-auth"] = 1
        runner.compose_json_stderr["supabase-auth"] = "unknown flag: --format"
        runner.compose_ps_q_stdout["supabase-auth"] = "auth-container\n"
        runner.inspect_state_stdout["auth-container"] = json.dumps(
            {"Status": "running", "Health": {"Status": "healthy"}, "ExitCode": 0}
        )

        state = _compose_service_state(
            process_runner=runner,
            compose_root=Path("/tmp/supabase"),
            compose_project_name="envctl-supabase-test",
            compose_path=Path("/tmp/supabase/docker-compose.yml"),
            env={},
            service_name="supabase-auth",
        )

        self.assertEqual(state.container_id, "auth-container")
        self.assertTrue(state.is_running)
        self.assertTrue(state.is_healthy)
        self.assertTrue(any(cmd[-3:] == ["ps", "-q", "supabase-auth"] for cmd in runner.commands))
        self.assertTrue(
            any(cmd[-1] == "auth-container" and cmd[:3] == ["docker", "inspect", "-f"] for cmd in runner.commands)
        )

    def test_handoff_ready_preserves_existing_created_container_semantics(self) -> None:
        runner = _ComposeStateRunner()
        runner.compose_json_stdout["supabase-db"] = json.dumps(
            [{"Service": "supabase-db", "ID": "db123", "State": "created"}]
        )

        self.assertTrue(
            _compose_services_ready_for_handoff(
                process_runner=runner,
                compose_root=Path("/tmp/supabase"),
                compose_project_name="envctl-supabase-test",
                compose_path=Path("/tmp/supabase/docker-compose.yml"),
                env={},
                service_names=["supabase-db"],
            )
        )

    def test_timeout_recovery_uses_json_compose_service_state(self) -> None:
        runner = _ComposeStateRunner()
        runner.compose_json_stdout["supabase-auth"] = json.dumps(
            [{"Service": "supabase-auth", "ID": "auth123", "State": "exited", "ExitCode": 1}]
        )

        self.assertTrue(
            _compose_timeout_recovered(
                process_runner=runner,
                compose_root=Path("/tmp/supabase"),
                compose_project_name="envctl-supabase-test",
                compose_path=Path("/tmp/supabase/docker-compose.yml"),
                env={},
                service_name="supabase-auth",
                probe_port=None,
                error="Command timed out after 120.0s: docker compose up -d supabase-auth",
            )
        )
        self.assertTrue(any(cmd[-4:] == ["ps", "--format", "json", "supabase-auth"] for cmd in runner.commands))
        self.assertFalse(any(cmd[-3:] == ["ps", "-q", "supabase-auth"] for cmd in runner.commands))

    def test_timeout_recovery_falls_back_to_inspected_service_state(self) -> None:
        runner = _ComposeStateRunner()
        runner.compose_json_returncode["supabase-auth"] = 1
        runner.compose_ps_q_stdout["supabase-auth"] = "auth-container\n"
        runner.inspect_state_stdout["auth-container"] = json.dumps({"Status": "created", "ExitCode": 0})

        self.assertTrue(
            _compose_timeout_recovered(
                process_runner=runner,
                compose_root=Path("/tmp/supabase"),
                compose_project_name="envctl-supabase-test",
                compose_path=Path("/tmp/supabase/docker-compose.yml"),
                env={},
                service_name="supabase-auth",
                probe_port=None,
                error="Command timed out after 120.0s: docker compose up -d supabase-auth",
            )
        )
        self.assertTrue(any(cmd[-3:] == ["ps", "-q", "supabase-auth"] for cmd in runner.commands))
        self.assertTrue(
            any(cmd[-1] == "auth-container" and cmd[:3] == ["docker", "inspect", "-f"] for cmd in runner.commands)
        )

    def test_timeout_recovery_rejects_missing_or_inspect_error_without_probe_port(self) -> None:
        missing_runner = _ComposeStateRunner()
        missing_runner.compose_json_stdout["missing"] = "[]"
        self.assertFalse(
            _compose_timeout_recovered(
                process_runner=missing_runner,
                compose_root=Path("/tmp/supabase"),
                compose_project_name="envctl-supabase-test",
                compose_path=Path("/tmp/supabase/docker-compose.yml"),
                env={},
                service_name="missing",
                probe_port=None,
                error="Command timed out after 120.0s: docker compose up -d missing",
            )
        )

        inspect_runner = _ComposeStateRunner()
        inspect_runner.compose_json_returncode["inspect-error"] = 1
        inspect_runner.compose_ps_q_stdout["inspect-error"] = "broken123\n"
        inspect_runner.inspect_returncode["broken123"] = 1
        inspect_runner.inspect_stderr["broken123"] = "inspect failed"
        self.assertFalse(
            _compose_timeout_recovered(
                process_runner=inspect_runner,
                compose_root=Path("/tmp/supabase"),
                compose_project_name="envctl-supabase-test",
                compose_path=Path("/tmp/supabase/docker-compose.yml"),
                env={},
                service_name="inspect-error",
                probe_port=None,
                error="Command timed out after 120.0s: docker compose up -d inspect-error",
            )
        )

    def test_timeout_recovery_keeps_probe_port_fallback(self) -> None:
        runner = _ComposeStateRunner()
        runner.compose_json_stdout["supabase-db"] = "[]"
        runner.wait_for_port_result = True

        self.assertTrue(
            _compose_timeout_recovered(
                process_runner=runner,
                compose_root=Path("/tmp/supabase"),
                compose_project_name="envctl-supabase-test",
                compose_path=Path("/tmp/supabase/docker-compose.yml"),
                env={},
                service_name="supabase-db",
                probe_port=5432,
                error="Command timed out after 120.0s: docker compose up -d supabase-db",
            )
        )
        self.assertEqual(runner.wait_for_port_calls, [(5432, 5.0)])


if __name__ == "__main__":
    unittest.main()
