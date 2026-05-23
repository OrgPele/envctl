# ruff: noqa: F403,F405
from __future__ import annotations

import unittest

from tests.python.requirements.requirements_adapter_contract_support import *


class SupabaseStackDbProbeContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
