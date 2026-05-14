from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from envctl_engine.requirements.supabase import (
    _compose_run,
    build_supabase_project_name,
    start_supabase_stack,
)
from tests.python.requirements.supabase_fakes import SupabaseFakeRunner


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
