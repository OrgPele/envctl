from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from envctl_engine.requirements.supabase import (
    _auth_recreate_probe_attempts,
    _auth_restart_probe_attempts,
    _condense_probe_error,
    _probe_supabase_auth_health,
    start_supabase_stack,
)
from tests.python.requirements.supabase_fakes import SupabaseFakeRunner, SupabaseFlakyHealthRunner


def _write_minimal_supabase_compose(root: Path) -> None:
    supabase_dir = root / "supabase"
    supabase_dir.mkdir(parents=True, exist_ok=True)
    (supabase_dir / "docker-compose.yml").write_text(
        "services:\n  supabase-db: {}\n  supabase-auth: {}\n  supabase-kong: {}\n",
        encoding="utf-8",
    )
    (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")


class SupabaseAuthRecoveryTests(unittest.TestCase):
    def test_auth_recovery_failure_keeps_compose_service_state_summaries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_minimal_supabase_compose(root)
            runner = SupabaseFakeRunner()
            runner.wait_for_port_sequences[54321] = [False, False, False, False, False, False]
            runner.compose_json_stdout["supabase-auth"] = json.dumps(
                [{"Service": "supabase-auth", "ID": "auth123", "State": "exited", "ExitCode": 1}]
            )
            runner.compose_json_stdout["supabase-kong"] = json.dumps(
                [{"Service": "supabase-kong", "ID": "kong123", "State": "running", "Health": "unhealthy"}]
            )

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "0.5"},
            )

        self.assertFalse(result.success)
        self.assertIn("service_state=", result.error or "")
        self.assertIn("supabase-auth", result.error or "")
        self.assertIn("status=exited", result.error or "")
        self.assertIn("supabase-kong", result.error or "")
        self.assertIn("health=unhealthy", result.error or "")
        inspect_events = [event for event in result.stage_events or [] if event.get("stage") == "supabase.auth.inspect"]
        self.assertTrue(inspect_events)


if __name__ == "__main__":
    unittest.main()


class SupabaseLegacyAuthRecoveryTests(unittest.TestCase):
    def test_supabase_auth_health_probe_retries_transient_http_failure(self) -> None:
        runner = SupabaseFlakyHealthRunner()

        ready, error = _probe_supabase_auth_health(
            process_runner=runner,
            public_port=54321,
            health_url="http://localhost:54321/auth/v1/health",
            env={"ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "1"},
        )

        self.assertTrue(ready)
        self.assertIsNone(error)
        self.assertEqual(runner.run_calls, 2)
        self.assertTrue(runner.sleep_calls)

    def test_supabase_auth_health_probe_does_not_surface_partial_urllib_traceback(self) -> None:
        class _PartialTracebackRunner:
            def wait_for_port(self, port: int, *, host: str = "127.0.0.1", timeout: float = 30.0) -> bool:
                _ = port, host, timeout
                return True

            def run(self, cmd, *, cwd=None, env=None, timeout=None, process_started_callback=None):  # noqa: ANN001
                _ = cwd, env, timeout, process_started_callback
                return subprocess.CompletedProcess(
                    list(cmd),
                    1,
                    "",
                    "Traceback (most recent call last):\n"
                    '  File "/usr/lib/python3.12/urllib/request.py", line 492, in _call_chain\n',
                )

            def sleep(self, seconds: float) -> None:
                _ = seconds

        ready, error = _probe_supabase_auth_health(
            process_runner=_PartialTracebackRunner(),
            public_port=54321,
            health_url="http://127.0.0.1:54321/auth/v1/health",
            env={"ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "0.5"},
        )

        self.assertFalse(ready)
        self.assertEqual(error, "HTTP health probe failed")
        self.assertNotIn("urllib/request.py", error or "")
        self.assertNotIn('File "', error or "")

    def test_supabase_auth_probe_error_condensing_ignores_traceback_frame_line_numbers(self) -> None:
        raw_error = (
            "ConnectionRefusedError: [Errno 111] Connection refused\n"
            '  File "/usr/lib/python3.12/urllib/request.py", line 492, in _call_chain\n'
        )

        self.assertEqual(
            _condense_probe_error(raw_error),
            "ConnectionRefusedError: [Errno 111] Connection refused",
        )

    def test_supabase_auth_recovery_defaults_allow_multiple_probe_windows(self) -> None:
        self.assertEqual(_auth_restart_probe_attempts({}), 2)
        self.assertEqual(_auth_recreate_probe_attempts({}), 3)

    def test_supabase_stack_fails_when_auth_kong_health_unreachable_after_db_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = False
            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_TWO_PHASE_STARTUP": "false"},
            )

            self.assertFalse(result.success)
            self.assertIn("Supabase DB is healthy but Supabase Auth/Kong is not reachable", result.error or "")
            self.assertIn("http://127.0.0.1:54321/auth/v1/health", result.error or "")
            self.assertIn("probe_url=http://127.0.0.1:54321/auth/v1/health", result.error or "")
            self.assertIn("actions=initial_probe,restart,recreate", result.error or "")
            self.assertNotIn("Traceback", result.error or "")
            self.assertNotIn('File "', result.error or "")
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-3:] == ["restart", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_auth_kong_failure_records_service_inspection_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = False
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["auth-container-id"] = "exited"
            runner.status["kong-container-id"] = "running"
            runner.health_status["kong-container-id"] = "starting"
            runner.state_error["auth-container-id"] = (
                "Traceback (most recent call last):\n"
                '  File "/app/auth.py", line 12, in boot\n'
                "SERVICE_ROLE_KEY=should-not-leak crashed"
            )

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_AUTH_RECREATE_PROBE_ATTEMPTS": "1"},
            )

            self.assertFalse(result.success)
            inspect_events = [
                item for item in result.stage_events or [] if item.get("stage") == "supabase.auth.inspect"
            ]
            self.assertGreaterEqual(len(inspect_events), 2)
            inspect_detail = " ".join(str(item.get("detail", "")) for item in inspect_events)
            self.assertIn("supabase-auth", inspect_detail)
            self.assertIn("status=exited", inspect_detail)
            self.assertIn("supabase-kong", inspect_detail)
            self.assertIn("status=running", inspect_detail)
            self.assertIn("health=starting", inspect_detail)
            self.assertIn("service_state=", result.error or "")
            self.assertIn("supabase-auth", result.error or "")
            self.assertIn("status=exited", result.error or "")
            self.assertIn("health=starting", result.error or "")
            self.assertNotIn("SERVICE_ROLE_KEY", result.error or "")
            self.assertNotIn("should-not-leak", result.error or "")
            self.assertNotIn("Traceback", result.error or "")
            self.assertNotIn('File "', result.error or "")

    def test_supabase_auth_kong_inspect_failure_is_summarized_without_blocking_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_sequences[54321] = [False, True]
            runner.compose_ps_q_returncode["supabase-auth"] = 1
            runner.compose_ps_q_stderr["supabase-auth"] = "compose ps failed"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_AUTH_RESTART_PROBE_ATTEMPTS": "1"},
            )

            self.assertTrue(result.success)
            inspect_events = [
                item for item in result.stage_events or [] if item.get("stage") == "supabase.auth.inspect"
            ]
            self.assertTrue(inspect_events)
            inspect_detail = " ".join(str(item.get("detail", "")) for item in inspect_events)
            self.assertIn("inspect_error", inspect_detail)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-3:] == ["restart", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_auth_kong_restart_recovers_when_listener_appears_late(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_sequences[54321] = [False, True]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_AUTH_RESTART_PROBE_ATTEMPTS": "1"},
            )

            self.assertTrue(result.success)
            self.assertFalse(result.container_recreated)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-3:] == ["restart", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            self.assertFalse(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_auth_kong_recreate_recovers_when_http_health_appears_late(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = True
            runner.health_returncode_by_phase = {"initial": [1], "restart": [1], "recreate": [0]}
            runner.health_stderr_by_phase = {
                "initial": [
                    "Traceback (most recent call last):\n"
                    "ConnectionRefusedError: [Errno 111] Connection refused"
                ],
                "restart": ["temporary 503"],
                "recreate": [""],
            }

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={
                    "ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "0.5",
                    "ENVCTL_SUPABASE_AUTH_RESTART_PROBE_ATTEMPTS": "1",
                    "ENVCTL_SUPABASE_AUTH_RECREATE_PROBE_ATTEMPTS": "1",
                },
            )

            self.assertTrue(result.success)
            self.assertTrue(result.container_recreated)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_auth_kong_recovery_does_not_recreate_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = False

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_AUTH_RECREATE_PROBE_ATTEMPTS": "1"},
            )

            self.assertFalse(result.success)
            self.assertFalse(
                any(cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["stop", "supabase-db"] for cmd in runner.commands)
            )
            self.assertFalse(
                any(
                    cmd[:2] == ["docker", "compose"] and cmd[-3:] == ["rm", "-f", "supabase-db"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_auth_probe_uses_local_loopback_when_public_url_is_remote(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54398] = True

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54398,
                env={"SUPABASE_PUBLIC_URL": "http://72.61.80.25:54398"},
            )

            self.assertTrue(result.success)
            self.assertEqual(runner.health_urls, ["http://127.0.0.1:54398/auth/v1/health"])

    def test_supabase_auth_recovery_respects_restart_and_recreate_env_toggles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = False

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={
                    "ENVCTL_SUPABASE_AUTH_RESTART_ON_PROBE_FAILURE": "false",
                    "ENVCTL_SUPABASE_AUTH_RECREATE_ON_PROBE_FAILURE": "false",
                    "ENVCTL_SUPABASE_AUTH_RESTART_PROBE_ATTEMPTS": "0",
                    "ENVCTL_SUPABASE_AUTH_RECREATE_PROBE_ATTEMPTS": "0",
                },
            )

            self.assertFalse(result.success)
            self.assertNotIn("restart", result.error or "")
            self.assertNotIn("recreate", result.error or "")
            self.assertFalse(any(cmd[:2] == ["docker", "compose"] and "restart" in cmd for cmd in runner.commands))
            self.assertFalse(any(cmd[:2] == ["docker", "compose"] and "rm" in cmd for cmd in runner.commands))

    def test_supabase_stack_starts_secondary_services_before_auth_health_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )

            self.assertTrue(result.success)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"] and cmd[-4:] == ["up", "-d", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
