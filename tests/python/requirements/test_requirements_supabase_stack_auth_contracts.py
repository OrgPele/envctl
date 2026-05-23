# ruff: noqa: F403,F405
from __future__ import annotations

import unittest

from tests.python.requirements.requirements_adapter_contract_support import *


class SupabaseStackAuthGatewayContractTests(unittest.TestCase):
    def test_supabase_auth_health_failure_reports_auth_phase_budget_elapsed_and_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_overrides[54321] = False
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["auth-container-id"] = "running"
            runner.status["kong-container-id"] = "running"
            runner.health_status["auth-container-id"] = "starting"
            runner.health_status["kong-container-id"] = "starting"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={
                    "ENVCTL_SUPABASE_STARTUP_TIMEOUT_SECONDS": "1",
                    "ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "0.5",
                    "ENVCTL_SUPABASE_AUTH_RESTART_ON_PROBE_FAILURE": "false",
                    "ENVCTL_SUPABASE_AUTH_RECREATE_ON_PROBE_FAILURE": "false",
                },
            )

            self.assertFalse(result.success)
            self.assertIn("phase=auth_health", result.error or "")
            self.assertIn("public_port=54321", result.error or "")
            self.assertIn("probe_url=http://127.0.0.1:54321/auth/v1/health", result.error or "")
            self.assertIn("auth_probe_timeout_s=0.5", result.error or "")
            self.assertIn("startup_budget_s=1", result.error or "")
            self.assertIn("elapsed_ms=", result.error or "")
            self.assertIn("service_state=", result.error or "")
            self.assertIn("health=starting", result.error or "")
            self.assertIn("last_error=listener probe failed on port 54321", result.error or "")

    def test_supabase_auth_kong_failure_records_service_inspection_summary(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
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

            runner = _FakeRunner()
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
                    cmd[:2] == ["docker", "compose"] and cmd[-3:] == ["restart", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_auth_kong_recovery_does_not_recreate_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
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

    def test_supabase_auth_kong_recreate_recovers_when_http_health_appears_late(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = True
            runner.health_returncode_by_phase = {"initial": [1], "restart": [1], "recreate": [0]}
            runner.health_stderr_by_phase = {
                "initial": [
                    "Traceback (most recent call last):\nConnectionRefusedError: [Errno 111] Connection refused"
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
                    cmd[:2] == ["docker", "compose"] and cmd[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_auth_kong_restart_recovers_when_service_state_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_sequences[54321] = [False, True]
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["auth-container-id"] = "exited"
            runner.status["kong-container-id"] = "running"

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
                    cmd[:2] == ["docker", "compose"] and cmd[-3:] == ["restart", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            self.assertFalse(
                any(
                    cmd[:2] == ["docker", "compose"] and cmd[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_auth_probe_uses_local_loopback_when_public_url_is_remote(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
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

    def test_supabase_auth_progress_waits_without_restart_when_public_health_appears_late(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_sequences[54321] = [False, True]
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["auth-container-id"] = "running"
            runner.status["kong-container-id"] = "running"
            runner.health_status["auth-container-id"] = "starting"
            runner.health_status["kong-container-id"] = "starting"
            runner.health_returncode_sequence = [0]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={
                    "ENVCTL_SUPABASE_STARTUP_TIMEOUT_SECONDS": "5",
                    "ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "0.5",
                },
            )

            self.assertTrue(result.success)
            self.assertFalse(
                any(
                    cmd[:2] == ["docker", "compose"] and cmd[-3:] == ["restart", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            self.assertFalse(
                any(
                    cmd[:2] == ["docker", "compose"] and cmd[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            self.assertTrue(
                any(item.get("stage") == "supabase.auth.wait_progress" for item in result.stage_events or [])
            )

    def test_supabase_auth_recovery_respects_restart_and_recreate_env_toggles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
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

    def test_supabase_stack_fails_when_auth_kong_health_unreachable_after_db_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
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
                    cmd[:2] == ["docker", "compose"] and cmd[-3:] == ["restart", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"] and cmd[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_recreates_auth_gateway_when_kong_uses_stale_public_port(self) -> None:
        class _Runner(_FakeRunner):
            def __init__(self) -> None:
                super().__init__()
                self.auth_gateway_removed = False
                self.graph_started = False

            def compose_up_process(self, cmd, *, cwd=None, env=None):  # noqa: ANN001
                compose_args = list(cmd)[list(cmd).index("-f") + 2 :] if "-f" in list(cmd) else list(cmd)
                if compose_args == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]:
                    self.graph_started = True
                    self.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
                    self.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
                    self.status["auth-container-id"] = "running"
                    self.status["kong-container-id"] = "running"
                    self.health_status["auth-container-id"] = "healthy"
                    self.health_status["kong-container-id"] = "healthy"
                    self.port_mappings[("kong-container-id", "8000")] = "0.0.0.0:54349\n"
                if self.auth_gateway_removed and compose_args == ["up", "-d", "supabase-auth", "supabase-kong"]:
                    self.port_mappings[("kong-container-id", "8000")] = "0.0.0.0:54321\n"
                return super().compose_up_process(cmd, cwd=cwd, env=env)

            def run(self, cmd, *, cwd=None, env=None, timeout=None, process_started_callback=None):  # noqa: ANN001
                result = super().run(
                    cmd,
                    cwd=cwd,
                    env=env,
                    timeout=timeout,
                    process_started_callback=process_started_callback,
                )
                command = list(cmd)
                if (
                    len(command) >= 4
                    and command[:2] == ["docker", "compose"]
                    and command[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                ):
                    self.auth_gateway_removed = True
                return result

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _Runner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_sequences[54321] = [True]
            runner.health_returncode_sequence = [0]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_STARTUP_TIMEOUT_SECONDS": "5"},
            )

            self.assertTrue(result.success)
            self.assertTrue(result.container_recreated)
            self.assertTrue(runner.graph_started)
            self.assertTrue(
                any(item.get("stage") == "supabase.gateway.port_mismatch" for item in result.stage_events or [])
            )
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"] and cmd[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_removes_stale_gateway_before_initial_graph_start(self) -> None:
        class _Runner(_FakeRunner):
            def __init__(self) -> None:
                super().__init__()
                self.auth_gateway_removed = False

            def compose_up_process(self, cmd, *, cwd=None, env=None):  # noqa: ANN001
                compose_args = list(cmd)[list(cmd).index("-f") + 2 :] if "-f" in list(cmd) else list(cmd)
                if self.auth_gateway_removed and compose_args == [
                    "up",
                    "-d",
                    "supabase-db",
                    "supabase-auth",
                    "supabase-kong",
                ]:
                    self.status["auth-container-id"] = "running"
                    self.status["kong-container-id"] = "running"
                    self.health_status["auth-container-id"] = "healthy"
                    self.health_status["kong-container-id"] = "healthy"
                    self.port_mappings[("kong-container-id", "8000")] = "0.0.0.0:54321\n"
                return super().compose_up_process(cmd, cwd=cwd, env=env)

            def run(self, cmd, *, cwd=None, env=None, timeout=None, process_started_callback=None):  # noqa: ANN001
                result = super().run(
                    cmd,
                    cwd=cwd,
                    env=env,
                    timeout=timeout,
                    process_started_callback=process_started_callback,
                )
                command = list(cmd)
                if (
                    len(command) >= 4
                    and command[:2] == ["docker", "compose"]
                    and command[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
                ):
                    self.auth_gateway_removed = True
                return result

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _Runner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_sequences[54321] = [True]
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["auth-container-id"] = "running"
            runner.status["kong-container-id"] = "created"
            runner.health_status["auth-container-id"] = "healthy"
            runner.port_mappings[("kong-container-id", "8000")] = "0.0.0.0:54349\n"
            runner.health_returncode_sequence = [0]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_STARTUP_TIMEOUT_SECONDS": "5"},
            )

            self.assertTrue(result.success)
            self.assertFalse(result.container_recreated)
            self.assertTrue(runner.auth_gateway_removed)
            self.assertTrue(
                any(
                    item.get("stage") == "supabase.gateway.port_mismatch.preflight"
                    and item.get("reason") == "remove_stale"
                    for item in result.stage_events or []
                )
            )
            preflight_index = next(
                index
                for index, cmd in enumerate(runner.commands)
                if cmd[:2] == ["docker", "compose"] and cmd[-4:] == ["rm", "-f", "supabase-auth", "supabase-kong"]
            )
            graph_up_index = next(
                index
                for index, cmd in enumerate(runner.commands)
                if cmd[:2] == ["docker", "compose"]
                and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
            )
            self.assertLess(preflight_index, graph_up_index)

    def test_supabase_timeout_recovery_for_auth_kong_requires_running_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            compose_path = supabase_dir / "docker-compose.yml"
            compose_path.write_text("services:\n  supabase-auth: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.status["auth-container-id"] = "created"

            created_recovered = _compose_timeout_recovered(
                process_runner=runner,
                compose_root=supabase_dir,
                compose_project_name="envctl-supabase-test",
                compose_path=compose_path,
                env={},
                service_name="supabase-auth",
                probe_port=None,
                error="Command timed out after 45.0s: docker compose up -d supabase-auth supabase-kong",
            )
            runner.status["auth-container-id"] = "running"
            running_recovered = _compose_timeout_recovered(
                process_runner=runner,
                compose_root=supabase_dir,
                compose_project_name="envctl-supabase-test",
                compose_path=compose_path,
                env={},
                service_name="supabase-auth",
                probe_port=None,
                error="Command timed out after 45.0s: docker compose up -d supabase-auth supabase-kong",
            )

            self.assertFalse(created_recovered)
            self.assertTrue(running_recovered)


if __name__ == "__main__":
    unittest.main()
