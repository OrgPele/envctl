from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from envctl_engine.requirements.core.registry import dependency_definition
from envctl_engine.requirements.supabase import (
    _compose_run,
    build_supabase_project_name,
    start_supabase_stack,
)
from tests.python.requirements.supabase_fakes import SupabaseFakeComposeProcess, SupabaseFakeRunner


def _write_minimal_supabase_compose(root: Path) -> None:
    supabase_dir = root / "supabase"
    supabase_dir.mkdir(parents=True, exist_ok=True)
    (supabase_dir / "docker-compose.yml").write_text(
        "services:\n  supabase-db: {}\n  supabase-auth: {}\n  supabase-kong: {}\n",
        encoding="utf-8",
    )
    (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\nSUPABASE_PUBLIC_PORT=54321\n", encoding="utf-8")


class SupabaseComposeStartupTests(unittest.TestCase):
    def test_compose_up_default_timeout_is_120_seconds(self) -> None:
        runner = SupabaseFakeRunner()
        captured: dict[str, float] = {}

        def _capture_handoff(**kwargs):  # noqa: ANN001
            captured["timeout_seconds"] = kwargs["timeout_seconds"]
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            compose_path = root / "docker-compose.yml"
            compose_path.write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            with mock.patch("envctl_engine.requirements.supabase._compose_up_handoff", side_effect=_capture_handoff):
                result = _compose_run(
                    process_runner=runner,
                    compose_root=root,
                    compose_project_name="envctl-supabase-test",
                    compose_path=compose_path,
                    env={},
                    args=["up", "-d", "supabase-db"],
                )

        self.assertIsNone(result)
        self.assertEqual(captured["timeout_seconds"], 120.0)

    def test_startup_preserves_managed_stage_order_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_minimal_supabase_compose(root)
            runner = SupabaseFakeRunner()

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "0.5"},
            )

        self.assertTrue(result.success, result.error)
        self.assertEqual(
            [event.get("stage") for event in result.stage_events or []],
            [
                "supabase.db.up",
                "supabase.db.probe",
                "supabase.secondary.up",
                "supabase.auth.probe",
                "supabase.auth.probe.final",
            ],
        )
        self.assertEqual(
            result.container_name,
            build_supabase_project_name(project_root=root, project_name="feature-a-1"),
        )

    def test_missing_network_recovery_records_stage_without_changing_service_retry_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_minimal_supabase_compose(root)
            runner = SupabaseFakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-db"] = [
                "failed to set up container networking: network abcdef123456 not found",
                "",
            ]

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "0.5"},
            )

        self.assertTrue(result.success, result.error)
        db_up_commands = [
            cmd
            for cmd in runner.commands
            if cmd[:2] == ["docker", "compose"] and cmd[-3:] == ["up", "-d", "supabase-db"]
        ]
        self.assertEqual(len(db_up_commands), 2)
        self.assertTrue(any(cmd[-2:] == ["down", "--remove-orphans"] for cmd in runner.commands))
        recovery_events = [
            event for event in result.stage_events or [] if event.get("stage") == "supabase.compose.network_recovery"
        ]
        self.assertTrue(recovery_events)
        self.assertIn("compose_down_remove_orphans", str(recovery_events[-1].get("detail", "")))

    def test_address_pool_recovery_retries_same_db_service_after_empty_network_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            _write_minimal_supabase_compose(root)
            runner = SupabaseFakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-db"] = [
                "all predefined address pools have been fully subnetted",
                "",
            ]
            runner.network_names = [
                "envctl-supabase-feature-a-1-deadbeef_default",
                "envctl-supabase-active_supabase-net",
            ]
            runner.network_container_counts = {
                "envctl-supabase-feature-a-1-deadbeef_default": 0,
                "envctl-supabase-active_supabase-net": 2,
            }

            result = start_supabase_stack(
                process_runner=runner,
                project_root=root,
                project_name="feature-a-1",
                db_port=5432,
                public_port=54321,
                env={"ENVCTL_SUPABASE_AUTH_PROBE_TIMEOUT_SECONDS": "0.5"},
            )

        self.assertTrue(result.success, result.error)
        db_up_commands = [
            cmd
            for cmd in runner.commands
            if cmd[:2] == ["docker", "compose"] and cmd[-3:] == ["up", "-d", "supabase-db"]
        ]
        self.assertEqual(len(db_up_commands), 2)
        removed_networks = [cmd[-1] for cmd in runner.commands if cmd[:3] == ["docker", "network", "rm"]]
        self.assertEqual(removed_networks, ["envctl-supabase-feature-a-1-deadbeef_default"])


if __name__ == "__main__":
    unittest.main()


class SupabaseLegacyComposeStartupTests(unittest.TestCase):
    def test_supabase_compose_up_default_timeout_is_120_seconds(self) -> None:
        runner = SupabaseFakeRunner()
        captured: dict[str, float] = {}

        def _capture_handoff(**kwargs):  # noqa: ANN001
            captured["timeout_seconds"] = kwargs["timeout_seconds"]
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            compose_path = root / "docker-compose.yml"
            compose_path.write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            with mock.patch("envctl_engine.requirements.supabase._compose_up_handoff", side_effect=_capture_handoff):
                result = _compose_run(
                    process_runner=runner,
                    compose_root=root,
                    compose_project_name="envctl-supabase-test",
                    compose_path=compose_path,
                    env={},
                    args=["up", "-d", "supabase-db"],
                )

        self.assertIsNone(result)
        self.assertEqual(captured["timeout_seconds"], 120.0)

    def test_supabase_stack_starts_compose_services_and_waits_for_db_port(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
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
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"] and cmd[-2:] == ["-d", "supabase-db"]
                    for cmd in runner.commands
                )
            )
            self.assertTrue(
                any(
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"]
                    and "supabase-auth" in cmd
                    and "supabase-kong" in cmd
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

            runner = SupabaseFakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-db"] = [
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
            db_ups = [
                cmd for cmd in runner.commands if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["-d", "supabase-db"]
            ]
            self.assertEqual(len(db_ups), 2)
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

            runner = SupabaseFakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-db"] = [
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
            db_ups = [
                cmd for cmd in runner.commands if cmd[:2] == ["docker", "compose"] and cmd[-2:] == ["-d", "supabase-db"]
            ]
            self.assertEqual(len(db_ups), 2)
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

            runner = SupabaseFakeRunner()
            runner.compose_returncode_sequence["up -d supabase-auth supabase-kong"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-auth supabase-kong"] = [
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
            secondary_ups = [
                cmd
                for cmd in runner.commands
                if cmd[:2] == ["docker", "compose"] and cmd[-4:] == ["up", "-d", "supabase-auth", "supabase-kong"]
            ]
            self.assertEqual(len(secondary_ups), 2)
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
            runner = SupabaseFakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db"] = [1, 0]
            runner.compose_stderr_sequence["up -d supabase-db"] = [
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

            runner = SupabaseFakeRunner()
            runner.compose_returncode_sequence["up -d supabase-db"] = [1, 1]
            runner.compose_stderr_sequence["up -d supabase-db"] = [
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
                build_supabase_project_name(project_root=root, project_name="feature-a-1"),
                result.error or "",
            )

    def test_supabase_stack_records_db_probe_stage_when_db_becomes_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
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
            db_probe_events = [
                item for item in result.stage_events or [] if item.get("stage") == "supabase.db.probe"
            ]
            self.assertTrue(db_probe_events)
            self.assertEqual(db_probe_events[-1].get("reason"), "ready")
            self.assertIn("port=5432", str(db_probe_events[-1].get("detail", "")))

    def test_supabase_stack_records_db_probe_stage_when_db_probe_exhausts(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
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
            db_probe_events = [
                item for item in result.stage_events or [] if item.get("stage") == "supabase.db.probe"
            ]
            self.assertTrue(db_probe_events)
            self.assertEqual(db_probe_events[-1].get("reason"), "failed")
            self.assertIn("attempts=2", str(db_probe_events[-1].get("detail", "")))

    def test_supabase_recovers_when_initial_up_times_out_but_service_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
            runner.compose_services_stdout = "supabase-db\n"
            runner.compose_ps_q_stdout["supabase-db"] = ["abc123\n", "abc123\n"]
            runner.wait_for_port_result = True

            def _hung_compose(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return SupabaseFakeComposeProcess(returncode=None)

            runner.compose_up_process = _hung_compose  # type: ignore[method-assign]

            with mock.patch("envctl_engine.requirements.supabase.os.killpg", side_effect=OSError()):
                result = start_supabase_stack(
                    process_runner=runner,
                    project_root=root,
                    project_name="feature-a-1",
                    db_port=5432,
                )

            self.assertTrue(result.success)

    def test_supabase_timeout_recovery_skips_repeated_db_up_when_service_already_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
            runner.compose_services_stdout = "supabase-db\n"
            runner.compose_ps_q_stdout["supabase-db"] = ["", "abc123\n", "abc123\n"]
            runner.wait_for_port_sequences[5432] = [False, True]

            def _hung_compose(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return SupabaseFakeComposeProcess(returncode=None)

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

    def test_supabase_handoffs_when_compose_cli_hangs_after_db_is_healthy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            (supabase_dir / ".env").write_text("SUPABASE_DB_PORT=5432\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
            runner.compose_services_stdout = "supabase-db\n"
            runner.compose_ps_q_stdout["supabase-db"] = ["", "abc123\n", "abc123\n"]
            runner.wait_for_port_sequences[5432] = [False, True]

            def _hung_compose(cmd, *, cwd=None, env=None):  # noqa: ANN001
                _ = cwd, env
                runner.commands.append(list(cmd))
                return SupabaseFakeComposeProcess(returncode=None)

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
            self.assertTrue(any(cmd[-3:] == ["ps", "-q", "supabase-db"] for cmd in runner.commands))

    def test_supabase_stack_uses_discovered_alternative_service_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text(
                "services:\n  db: {}\n  auth: {}\n  kong: {}\n", encoding="utf-8"
            )

            runner = SupabaseFakeRunner()
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
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"] and cmd[-2:] == ["-d", "db"]
                    for cmd in runner.commands
                )
            )
            self.assertTrue(
                any(
                    cmd[:5] == ["docker", "compose", "-p", compose_project, "-f"] and "auth" in cmd and "kong" in cmd
                    for cmd in runner.commands
                )
            )

    def test_supabase_stack_fails_when_compose_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runner = SupabaseFakeRunner()
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

            runner = SupabaseFakeRunner()
            runner.wait_for_port_sequences[5432] = [False, True]

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
            self.assertGreaterEqual(len(db_ups), 2)

    def test_supabase_stack_fails_after_db_probe_retry_exhausted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            supabase_dir = root / "supabase"
            supabase_dir.mkdir(parents=True, exist_ok=True)
            (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            runner = SupabaseFakeRunner()
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

            runner = SupabaseFakeRunner()
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

            runner = SupabaseFakeRunner()
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

            runner = SupabaseFakeRunner()
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

            runner = SupabaseFakeRunner()
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

    def test_supabase_stack_uses_unique_compose_project_name_per_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            first = root / "trees" / "feature-a" / "1"
            second = root / "trees" / "feature-b" / "1"
            for path in (first, second):
                supabase_dir = path / "supabase"
                supabase_dir.mkdir(parents=True, exist_ok=True)
                (supabase_dir / "docker-compose.yml").write_text("services:\n  supabase-db: {}\n", encoding="utf-8")

            first_runner = SupabaseFakeRunner()
            second_runner = SupabaseFakeRunner()

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

            runner = SupabaseFakeRunner()
            runner.compose_returncode["up -d supabase-db"] = 1
            runner.compose_stderr["up -d supabase-db"] = (
                "Container supabase-supabase-db-1 Error response from daemon: Conflict. "
                'The container name "/supabase-supabase-db-1" is already in use by container "abc".\n'
                "Error response from daemon: Conflict. "
                'The container name "/supabase-supabase-db-1" is already in use by container "abc".'
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
