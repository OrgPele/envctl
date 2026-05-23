# ruff: noqa: F403,F405
from __future__ import annotations

import unittest

from tests.python.requirements.requirements_adapter_contract_support import *


class SupabaseStackContractTests(unittest.TestCase):
    def test_supabase_stack_starts_compose_services_and_waits_for_db_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_TWO_PHASE_STARTUP": "false"},
            )
            self.assertTrue(result.success)
            compose_project = build_supabase_project_name(project_root=root, project_name="feature-a-1")
            self.assertEqual(result.container_name, compose_project)
            self.assertTrue(
                any(
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"] and "config" in cmd
                    for cmd in runner.commands
                )
            )
            self.assertTrue(
                any(
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"]
                    and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_stack_recovers_address_pool_exhaustion_by_removing_empty_envctl_supabase_networks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db supabase-auth supabase-kong"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-db supabase-auth supabase-kong"] = [
                "Error response from daemon: all predefined address pools have been fully subnetted",
                "",
            ]
            runner.network_names = [
                "envctl-supabase-main-deadbeef_default",
                "envctl-supabase-main-deadbeef_supabase-net",
                "envctl-redis-main-deadbeef_default",
                "bridge",
                "envctl-supabase-active_supabase-net",
            ]
            runner.network_container_counts = {
                "envctl-supabase-active_supabase-net": 1,
            }

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_TWO_PHASE_STARTUP": "false"},
            )

            self.assertTrue(result.success)
            graph_ups = [
                cmd
                for cmd in runner.commands
                if cmd[:2] == ["docker", "compose"]
                and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
            ]
            self.assertEqual(len(graph_ups), 2)
            removed_networks = [cmd[-1] for cmd in runner.commands if cmd[:3] == ["docker", "network", "rm"]]
            self.assertEqual(
                removed_networks,
                [
                    "envctl-supabase-main-deadbeef_default",
                    "envctl-supabase-main-deadbeef_supabase-net",
                ],
            )
            self.assertNotIn("envctl-redis-main-deadbeef_default", removed_networks)
            self.assertNotIn("envctl-supabase-active_supabase-net", removed_networks)

    def test_supabase_stack_recovers_missing_network_during_db_up_with_scoped_compose_down(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db supabase-auth supabase-kong"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-db supabase-auth supabase-kong"] = [
                "failed to set up container networking: network 3b2e1a0f9d8c not found",
                "",
            ]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
            )

            self.assertTrue(result.success)
            compose_project = build_supabase_project_name(project_root=root, project_name="feature-a-1")
            graph_ups = [
                cmd
                for cmd in runner.commands
                if cmd[:2] == ["docker", "compose"]
                and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
            ]
            self.assertEqual(len(graph_ups), 2)
            self.assertTrue(
                any(
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"]
                    and cmd[-2:] == ["down", "--remove-orphans"]
                    for cmd in runner.commands
                )
            )
            network_events = [
                item for item in result.stage_events or [] if item.get("stage") == "supabase.compose.network_recovery"
            ]
            self.assertTrue(network_events)
            self.assertIn("compose_down_remove_orphans", str(network_events[-1].get("detail", "")))
            self.assertFalse(any(cmd[:3] == ["docker", "network", "rm"] for cmd in runner.commands))

    def test_supabase_stack_recovers_missing_network_during_secondary_up(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db supabase-auth supabase-kong"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-db supabase-auth supabase-kong"] = [
                "failed to set up container networking: network 0123456789abcdef not found",
                "",
            ]
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = True

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
            )

            self.assertTrue(result.success)
            graph_ups = [
                cmd
                for cmd in runner.commands
                if cmd[:2] == ["docker", "compose"]
                and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
            ]
            self.assertEqual(len(graph_ups), 2)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["down", "--remove-orphans"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_stack_records_db_probe_stage_when_db_becomes_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = True

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
            )

            self.assertTrue(result.success)
            db_probe_events = [item for item in result.stage_events or [] if item.get("stage") == "supabase.db.probe"]
            self.assertTrue(db_probe_events)
            self.assertEqual(db_probe_events[-1].get("reason"), "ready")
            self.assertIn("port=5432", str(db_probe_events[-1].get("detail", "")))

    def test_supabase_stack_records_db_probe_stage_when_db_probe_exhausts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_DB_RESTART_ON_PROBE_FAILURE": "false"},
            )

            self.assertFalse(result.success)
            db_probe_events = [item for item in result.stage_events or [] if item.get("stage") == "supabase.db.probe"]
            self.assertTrue(db_probe_events)
            self.assertEqual(db_probe_events[-1].get("reason"), "failed")
            self.assertIn("attempts=2", str(db_probe_events[-1].get("detail", "")))

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

    def test_supabase_stack_starts_full_graph_before_auth_health_probe(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )

            self.assertTrue(result.success)
            graph_ups = [
                cmd
                for cmd in runner.commands
                if cmd[:2] == ["docker", "compose"]
                and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
            ]
            self.assertEqual(len(graph_ups), 1)
            self.assertFalse(
                any(
                    cmd[:2] == ["docker", "compose"] and cmd[-4:] == ["up", "-d", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            stage_names = [str(item.get("stage", "")) for item in result.stage_events or []]
            self.assertIn("supabase.graph.up", stage_names)
            self.assertIn("supabase.db.probe", stage_names)
            self.assertIn("supabase.auth.probe", stage_names)

    def test_supabase_stack_uses_discovered_alternative_service_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text(
                "services:\n  db: {}\n  auth: {}\n  kong: {}\n", encoding="utf-8"
            )

            runner = _FakeRunner()
            runner.compose_services_stdout = "db\nauth\nkong\n"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertTrue(result.success)
            compose_project = build_supabase_project_name(project_root=root, project_name="feature-a-1")
            self.assertTrue(
                any(
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"]
                    and cmd[-5:] == ["up", "-d", "db", "auth", "kong"]
                    for cmd in runner.commands
                )
            )

    def test_supabase_stack_fails_when_compose_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = _FakeRunner()
            result = start_supabase_stack(
                process_runner=runner,
                project_root=Path(tmpdir),
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertFalse(result.success)
            self.assertIn("missing supabase compose file", result.error or "")

    def test_supabase_stack_retries_db_bringup_when_initial_probe_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, True]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertTrue(result.success)
            graph_ups = [
                cmd
                for cmd in runner.commands
                if cmd[:2] == ["docker", "compose"]
                and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
            ]
            db_retry_ups = [
                cmd for cmd in runner.commands if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["-d", "supabase-db"]
            ]
            self.assertEqual(len(graph_ups), 1)
            self.assertGreaterEqual(len(db_retry_ups), 1)

    def test_supabase_stack_fails_after_db_probe_retry_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                env={"ENVCTL_SUPABASE_DB_RESTART_ON_PROBE_FAILURE": "false"},
            )
            self.assertFalse(result.success)
            self.assertIn("after retry", result.error or "")

    def test_supabase_stack_restarts_db_after_probe_exhaustion_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False, True]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertTrue(result.success)
            restart_seen = any(
                cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["restart", "supabase-db"] for cmd in runner.commands
            )
            self.assertTrue(restart_seen)

    def test_supabase_stack_reports_restart_failure_when_restart_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False]
            runner.compose_returncode["restart supabase-db"] = 1
            runner.compose_stderr["restart supabase-db"] = "restart failed"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertFalse(result.success)
            self.assertIn("failed restarting supabase db service", result.error or "")

    def test_supabase_stack_recreates_db_after_restart_probe_exhaustion_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False, False, False, True]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertTrue(result.success)
            restart_seen = any(
                cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["restart", "supabase-db"] for cmd in runner.commands
            )
            stop_seen = any(
                cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["stop", "supabase-db"] for cmd in runner.commands
            )
            rm_seen = any(
                cmd[:2] == ["docker", "compose"] and cmd[-3:] == ["rm", "-f", "supabase-db"] for cmd in runner.commands
            )
            self.assertTrue(restart_seen)
            self.assertTrue(stop_seen)
            self.assertTrue(rm_seen)

    def test_supabase_stack_reports_recreate_failure_when_recreate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False, False, False]
            runner.compose_returncode["rm -f supabase-db"] = 1
            runner.compose_stderr["rm -f supabase-db"] = "remove failed"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )
            self.assertFalse(result.success)
            self.assertIn("failed recreating supabase db service", result.error or "")

    def test_supabase_stack_uses_unique_compose_project_name_per_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "trees" / "feature-a" / "1"
            second = root / "trees" / "feature-b" / "1"
            for path in (first, second):
                supabase_dir = path / "supabase"
                supabase_dir.mkdir(parents=True, exist_ok=True)
                (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            first_runner = _FakeRunner()
            second_runner = _FakeRunner()

            first_result = start_supabase_stack(
                process_runner=first_runner,
                project_root=first,
                project_name="feature-a-1",
                db_port=5432,
            )
            second_result = start_supabase_stack(
                process_runner=second_runner,
                project_root=second,
                project_name="feature-b-1",
                db_port=5433,
            )

            self.assertTrue(first_result.success)
            self.assertTrue(second_result.success)
            self.assertNotEqual(first_result.container_name, second_result.container_name)

    def test_supabase_stack_condenses_container_name_conflict_into_actionable_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode["up -d supabase-db supabase-auth supabase-kong"] = 1
            runner.compose_stderr["up -d supabase-db supabase-auth supabase-kong"] = (
                "Container supabase-supabase-db-1 Error response from daemon: Conflict. "
                'The container name "/supabase-supabase-db-1" is already in use by container "abc".\n'
                'Error response from daemon: Conflict. The container name "/supabase-supabase-db-1" is already in use by container "abc".'
            )

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
            )

            self.assertFalse(result.success)
            self.assertIn("supabase compose namespace conflict", result.error or "")
            self.assertIn("supabase-supabase-db-1", result.error or "")

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

    def test_supabase_compose_handoff_does_not_treat_created_service_as_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            compose_path = supabase_dir / "docker-compose.yml"
            compose_path.write_text("services:\n  supabase-auth: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.status["auth-container-id"] = "created"

            ready = _compose_services_started(
                process_runner=runner,
                compose_root=supabase_dir,
                compose_project_name="envctl-supabase-test",
                compose_path=compose_path,
                env={},
                service_names=["supabase-auth"],
            )

            self.assertFalse(ready)

    def test_supabase_compose_timeout_override_does_not_exceed_overall_startup_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [True]
            runner.wait_for_port_sequences[54321] = [True]
            runner.health_returncode_sequence = [0]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={
                    "ENVCTL_SUPABASE_STARTUP_TIMEOUT_SECONDS": "1",
                    "ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS": "45",
                },
            )

            self.assertTrue(result.success)
            graph_event = next(item for item in result.stage_events or [] if item.get("stage") == "supabase.graph.up")
            self.assertEqual(graph_event.get("timeout_s"), 1.0)
            self.assertEqual(graph_event.get("startup_budget_s"), 1.0)

    def test_supabase_db_probe_failure_reports_phase_budget_elapsed_and_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.wait_for_port_sequences[5432] = [False, False]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={
                    "ENVCTL_SUPABASE_DB_RESTART_ON_PROBE_FAILURE": "false",
                    "ENVCTL_SUPABASE_DB_PROBE_TIMEOUT_SECONDS": "0.5",
                    "ENVCTL_SUPABASE_STARTUP_TIMEOUT_SECONDS": "5",
                },
            )

            self.assertFalse(result.success)
            self.assertIn("phase=db_probe", result.error or "")
            self.assertIn("db_port=5432", result.error or "")
            self.assertIn("db_probe_timeout_s=0.5", result.error or "")
            self.assertIn("attempts=2", result.error or "")
            self.assertIn("startup_budget_s=5", result.error or "")
            self.assertIn("elapsed_ms=", result.error or "")
            self.assertIn("last_error=probe timeout waiting for readiness on port 5432 after retry", result.error or "")

    def test_supabase_graph_handoff_does_not_finish_when_only_db_is_ready(self) -> None:
        runner = _FakeRunner()
        runner.wait_for_port_result = True
        runner.compose_up_process = lambda *args, **kwargs: _FakeComposeProcess(returncode=None)  # type: ignore[method-assign]
        runner.status["supabase-db-container-id"] = "running"
        runner.health_status["supabase-db-container-id"] = "healthy"
        runner.status["supabase-auth-container-id"] = "created"
        runner.status["supabase-kong-container-id"] = "created"
        runner.port_mappings[("supabase-db-container-id", "5432")] = "0.0.0.0:5432\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            compose_path = root / "docker-compose.yml"
            compose_path.write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (root / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            result = _compose_run(
                process_runner=runner,
                compose_root=root,
                compose_project_name="envctl-supabase-test",
                compose_path=compose_path,
                env={"ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS": "5"},
                args=["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"],
            )

        self.assertIsNotNone(result)
        self.assertIn("Command timed out after 5.0s", result or "")
        self.assertIn("supabase-auth", result or "")

    def test_supabase_graph_startup_does_not_fail_when_auth_kong_progress_past_old_compose_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_ps_q_stdout["supabase-db"] = "db-container-id\n"
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["db-container-id"] = "running"
            runner.status["auth-container-id"] = "running"
            runner.status["kong-container-id"] = "running"
            runner.health_status["kong-container-id"] = "healthy"
            runner.wait_for_port_overrides[5432] = True
            runner.wait_for_port_overrides[54321] = True
            runner.health_returncode_sequence = [0]

            def _hung_graph(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return _FakeComposeProcess(returncode=None)

            runner.compose_up_process = _hung_graph  # type: ignore[method-assign]

            with mock.patch("envctl_engine.requirements.supabase.os.killpg", side_effect=OSError()):
                result = start_supabase_stack(
                    process_runner=runner,
                    project_root=root,
                    project_name="feature-a-1",
                    db_port=5432,
                    public_port=54321,
                )

            self.assertTrue(result.success)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "compose"]
                    and cmd[-5:] == ["up", "-d", "supabase-db", "supabase-auth", "supabase-kong"]
                    for cmd in runner.commands
                )
            )
            self.assertEqual(runner.health_urls, ["http://127.0.0.1:54321/auth/v1/health"])

    def test_supabase_graph_startup_failure_reports_phase_timeout_port_and_service_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode["up -d supabase-db supabase-auth supabase-kong"] = 1
            runner.compose_stderr["up -d supabase-db supabase-auth supabase-kong"] = (
                "Container supabase-kong-1 Starting"
            )
            runner.compose_ps_q_stdout["supabase-db"] = "db-container-id\n"
            runner.compose_ps_q_stdout["supabase-auth"] = "auth-container-id\n"
            runner.compose_ps_q_stdout["supabase-kong"] = "kong-container-id\n"
            runner.status["db-container-id"] = "running"
            runner.status["auth-container-id"] = "running"
            runner.status["kong-container-id"] = "created"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_COMPOSE_UP_TIMEOUT_SECONDS": "45"},
            )

            self.assertFalse(result.success)
            self.assertIn("phase=compose_graph", result.error or "")
            self.assertIn("compose_timeout_s=45", result.error or "")
            self.assertIn("public_port=54321", result.error or "")
            self.assertIn("probe_url=http://127.0.0.1:54321/auth/v1/health", result.error or "")
            self.assertIn("supabase-kong", result.error or "")
            self.assertIn("status=created", result.error or "")
            self.assertIn("last_error=Container supabase-kong-1 Starting", result.error or "")
            self.assertIn("startup_budget_s=120", result.error or "")
            self.assertIn("elapsed_ms=", result.error or "")

    def test_supabase_handoffs_when_compose_cli_hangs_after_db_is_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_services_stdout = "supabase-db\n"
            runner.compose_ps_q_stdout["supabase-db"] = ["", "abc123\n", "abc123\n"]
            runner.wait_for_port_sequences[5432] = [False, True]

            def _hung_compose(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return _FakeComposeProcess(returncode=None)

            runner.compose_up_process = _hung_compose  # type: ignore[method-assign]

            with mock.patch("envctl_engine.requirements.supabase.os.killpg", side_effect=OSError()):
                result = start_supabase_stack(
                    process_runner=runner,
                    project_root=root,
                    project_name="feature-a-1",
                    db_port=5432,
                )

            self.assertTrue(result.success)
            db_ups = [
                cmd for cmd in runner.commands if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["-d", "supabase-db"]
            ]
            self.assertEqual(len(db_ups), 1)
            self.assertTrue(any(cmd[-4:] == ["ps", "--format", "json", "supabase-db"] for cmd in runner.commands))

    def test_supabase_missing_network_recovery_does_not_remove_other_worktree_or_non_empty_networks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            compose_project = build_supabase_project_name(project_root=root, project_name="feature-a-1")
            runner = _FakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db supabase-auth supabase-kong"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-db supabase-auth supabase-kong"] = [
                "Error response from daemon: failed to set up container networking: network 0123456789ab not found",
                "",
            ]
            runner.compose_returncode["down --remove-orphans"] = 1
            runner.compose_stderr["down --remove-orphans"] = "compose down failed"
            runner.network_names = [
                f"{compose_project}_default",
                f"{compose_project}_supabase-net",
                f"{compose_project}_other",
                f"{compose_project}_supabase-net_nonempty",
                "envctl-supabase-otherworktree_default",
                "envctl-redis-main-deadbeef_default",
                "bridge",
            ]
            runner.network_container_counts = {
                f"{compose_project}_supabase-net_nonempty": 2,
                "envctl-supabase-otherworktree_default": 0,
            }

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
            )

            self.assertTrue(result.success)
            removed_networks = [cmd[-1] for cmd in runner.commands if cmd[:3] == ["docker", "network", "rm"]]
            self.assertEqual(removed_networks, [f"{compose_project}_default", f"{compose_project}_supabase-net"])
            self.assertNotIn(f"{compose_project}_supabase-net_nonempty", removed_networks)
            self.assertNotIn("envctl-supabase-otherworktree_default", removed_networks)
            self.assertNotIn("envctl-redis-main-deadbeef_default", removed_networks)

    def test_supabase_missing_network_recovery_reports_exhausted_scoped_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db supabase-auth supabase-kong"] = [1, 1]
            runner.compose_stderr_sequence["up -d supabase-db supabase-auth supabase-kong"] = [
                "failed to set up container networking: network 0123456789ab not found",
                "still missing network",
            ]
            runner.compose_returncode["down --remove-orphans"] = 1
            runner.compose_stderr["down --remove-orphans"] = "compose down failed"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
            )

            self.assertFalse(result.success)
            self.assertIn("scoped Supabase network recovery", result.error or "")
            self.assertIn("compose_down_error=compose down failed", result.error or "")
            self.assertIn("still missing network", result.error or "")
            self.assertIn(
                build_supabase_project_name(project_root=root, project_name="feature-a-1"), result.error or ""
            )

    def test_supabase_project_env_exports_database_url_and_password(self) -> None:
        class _Runtime:
            @staticmethod
            def _command_override_value(key: str) -> str | None:
                return {
                    "SUPABASE_ANON_KEY": "anon-secret",
                    "SUPABASE_SERVICE_ROLE_KEY": "service-secret",
                    "SUPABASE_JWT_SECRET": "jwt-secret",
                }.get(key)

        class _Context:
            ports = {"db": type("Plan", (), {"final": 5432})()}

        class _Requirements:
            @staticmethod
            def component(name: str) -> dict[str, object]:
                assert name == "supabase"
                return {"final": 5432, "requested": 5432}

        env_projector = dependency_definition("supabase").env_projector
        assert env_projector is not None
        env = env_projector(runtime=_Runtime(), context=_Context(), requirements=_Requirements(), route=None)

        self.assertEqual(env["DB_HOST"], "localhost")
        self.assertEqual(env["DB_PORT"], "5432")
        self.assertEqual(env["DB_USER"], "postgres")
        self.assertEqual(env["DB_PASSWORD"], "supabase-db-password")
        self.assertIn("supabase-db-password", env["DATABASE_URL"])
        self.assertEqual(env["DATABASE_URL"], env["SQLALCHEMY_DATABASE_URL"])
        self.assertEqual(env["DATABASE_URL"], env["ASYNC_DATABASE_URL"])
        self.assertEqual(env["SUPABASE_URL"], "http://localhost:5432")
        self.assertEqual(env["SUPABASE_ANON_KEY"], "anon-secret")
        self.assertEqual(env["SUPABASE_SERVICE_ROLE_KEY"], "service-secret")
        self.assertEqual(env["SUPABASE_JWT_SECRET"], "jwt-secret")
        self.assertEqual(env["SUPABASE_JWKS_URL"], "http://localhost:5432/auth/v1/.well-known/jwks.json")

    def test_supabase_recovers_when_initial_up_times_out_but_service_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_services_stdout = "supabase-db\n"
            runner.compose_ps_q_stdout["supabase-db"] = ["abc123\n", "abc123\n"]
            runner.wait_for_port_result = True

            def _hung_compose(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return _FakeComposeProcess(returncode=None)

            runner.compose_up_process = _hung_compose  # type: ignore[method-assign]

            with mock.patch("envctl_engine.requirements.supabase.os.killpg", side_effect=OSError()):
                result = start_supabase_stack(
                    process_runner=runner,
                    project_root=root,
                    project_name="feature-a-1",
                    db_port=5432,
                )

            self.assertTrue(result.success)

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

    def test_supabase_timeout_recovery_skips_repeated_db_up_when_service_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = _FakeRunner()
            runner.compose_services_stdout = "supabase-db\n"
            runner.compose_ps_q_stdout["supabase-db"] = ["", "abc123\n", "abc123\n"]
            runner.wait_for_port_sequences[5432] = [False, True]

            def _hung_compose(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return _FakeComposeProcess(returncode=None)

            runner.compose_up_process = _hung_compose  # type: ignore[method-assign]

            with mock.patch("envctl_engine.requirements.supabase.os.killpg", side_effect=OSError()):
                result = start_supabase_stack(
                    process_runner=runner,
                    project_root=root,
                    project_name="feature-a-1",
                    db_port=5432,
                )

            self.assertTrue(result.success)
            db_ups = [
                cmd for cmd in runner.commands if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["-d", "supabase-db"]
            ]
            self.assertEqual(len(db_ups), 1)


if __name__ == "__main__":
    unittest.main()
