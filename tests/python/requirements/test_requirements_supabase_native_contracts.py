# ruff: noqa: F403,F405
from __future__ import annotations

import inspect
import unittest

from envctl_engine.requirements.supabase_lifecycle import native_db
from tests.python.requirements.requirements_adapter_contract_support import *


class SupabaseNativeDbContractTests(unittest.TestCase):
    def test_supabase_native_db_startup_has_lifecycle_owner(self) -> None:
        self.assertTrue(hasattr(native_db, "NativeSupabaseDatabaseStarter"))
        start_lines, _ = inspect.getsourcelines(native_db._start_supabase_db_native)
        self.assertLessEqual(len(start_lines), 35)

    def test_supabase_native_db_recovers_from_timed_out_start_when_container_becomes_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.existing.add(container_name)
            runner.status[container_name] = "exited"
            runner.port_mappings[(container_name, "5432")] = "0.0.0.0:5435\n"
            runner.start_timeout.add(container_name)

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.container_name, container_name)
            self.assertEqual(result.effective_port, 5435)
            self.assertTrue(
                any(cmd[:2] == ["docker", "start"] and cmd[-1] == container_name for cmd in runner.commands)
            )

    def test_supabase_native_db_start_timeout_surfaces_bind_conflict_state_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.existing.add(container_name)
            runner.status[container_name] = "created"
            runner.port_mappings[(container_name, "5432")] = "0.0.0.0:5435\n"
            runner.start_timeout.add(container_name)
            runner.state_error[container_name] = "Bind for 0.0.0.0:5435 failed: port is already allocated"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertFalse(result.success)
            self.assertIn("port is already allocated", result.error or "")

    def test_supabase_native_db_start_timeout_surfaces_missing_published_port_as_bind_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.existing.add(container_name)
            runner.status[container_name] = "created"
            runner.port_mappings[(container_name, "5432")] = "0.0.0.0:5435\n"
            runner.network_port_mappings[(container_name, "5432")] = None
            runner.start_timeout.add(container_name)

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertFalse(result.success)
            self.assertIn("published host port missing", result.error or "")

    def test_supabase_native_db_start_timeout_recovers_when_published_port_appears_late(self) -> None:
        class _RecoveringRunner(_FakeRunner):
            def sleep(self, seconds: float) -> None:
                super().sleep(seconds)
                if len(self.sleep_calls) >= 2:
                    self.network_port_mappings[(container_name, "5432")] = "0.0.0.0:5435\n"

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _RecoveringRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.existing.add(container_name)
            runner.status[container_name] = "created"
            runner.port_mappings[(container_name, "5432")] = "0.0.0.0:5435\n"
            runner.network_port_mappings[(container_name, "5432")] = None
            runner.start_timeout.add(container_name)

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 5435)
            self.assertGreaterEqual(len(runner.sleep_calls), 2)

    def test_supabase_native_db_recreates_existing_container_without_host_port_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.existing.add(container_name)
            runner.status[container_name] = "running"

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.container_name, container_name)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            create_seen = any(
                cmd[:2] == ["docker", "create"] and "--name" in cmd and container_name in cmd for cmd in runner.commands
            )
            self.assertTrue(rm_seen)
            self.assertTrue(create_seen)

    def test_supabase_native_db_recreates_existing_container_when_host_probe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.existing.add(container_name)
            runner.status[container_name] = "running"
            runner.port_mappings[(container_name, "5432")] = "0.0.0.0:5435\n"
            runner.wait_for_port_sequences[5435] = [False, True]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertTrue(result.success)
            rm_seen = any(cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name for cmd in runner.commands)
            create_seen = any(
                cmd[:2] == ["docker", "create"] and "--name" in cmd and container_name in cmd for cmd in runner.commands
            )
            self.assertTrue(rm_seen)
            self.assertTrue(create_seen)

    def test_supabase_native_db_recreates_mismatched_adopted_container_when_host_probe_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.existing.add(container_name)
            runner.status[container_name] = "running"
            runner.port_mappings[(container_name, "5432")] = "0.0.0.0:5440\n"
            runner.wait_for_port_sequences[5440] = [False]
            runner.wait_for_port_sequences[5435] = [True]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.effective_port, 5435)
            self.assertFalse(result.port_adopted)
            rm_commands = [cmd for cmd in runner.commands if cmd[:3] == ["docker", "rm", "-f"] and cmd[-1] == container_name]
            self.assertEqual(len(rm_commands), 1)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "create"] and "--name" in cmd and container_name in cmd
                    for cmd in runner.commands
                )
            )

    def test_supabase_native_db_recovers_from_timed_out_create_when_container_becomes_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            runner = _FakeRunner()
            container_name = build_supabase_project_name(project_root=root, project_name="Main") + "-supabase-db-1"
            runner.create_timeout.add(container_name)

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="Main",
                db_port=5435,
                env={"ENVCTL_SUPABASE_DB_START_NATIVE": "true"},
            )

            self.assertTrue(result.success)
            self.assertEqual(result.container_name, container_name)
            self.assertEqual(result.effective_port, 5435)
            self.assertTrue(
                any(
                    cmd[:2] == ["docker", "create"] and "--name" in cmd and container_name in cmd
                    for cmd in runner.commands
                )
            )
            self.assertTrue(
                any(cmd[:2] == ["docker", "start"] and cmd[-1] == container_name for cmd in runner.commands)
            )


if __name__ == "__main__":
    unittest.main()
