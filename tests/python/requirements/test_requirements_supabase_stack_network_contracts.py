# ruff: noqa: F403,F405
from __future__ import annotations

import unittest

from tests.python.requirements.requirements_adapter_contract_support import *


class SupabaseStackNetworkRecoveryContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
