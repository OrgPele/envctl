from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

from envctl_engine.requirements.supabase_lifecycle.db_flow import ensure_supabase_db_ready
from envctl_engine.requirements.supabase_lifecycle.types import _SupabaseStartupBudget


class _Runner:
    def __init__(self, port_sequence: list[bool]) -> None:
        self.port_sequence = list(port_sequence)
        self.commands: list[list[str]] = []

    def wait_for_port(self, _port: int, *, timeout: float) -> bool:
        _ = timeout
        if self.port_sequence:
            return self.port_sequence.pop(0)
        return False

    def run(self, cmd, *, cwd=None, env=None, timeout=None, process_started_callback=None):  # noqa: ANN001
        _ = cwd, env, timeout, process_started_callback
        command = list(cmd)
        self.commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


class SupabaseDbFlowTests(unittest.TestCase):
    def test_ensure_db_ready_records_initial_success(self) -> None:
        stage_events: list[dict[str, object]] = []
        result = ensure_supabase_db_ready(
            process_runner=_Runner([True]),
            compose_root=Path("/repo/supabase"),
            compose_project_name="envctl-test-supabase",
            compose_path=Path("/repo/supabase/docker-compose.yml"),
            env={},
            db_service="supabase-db",
            graph_services=["supabase-db", "supabase-auth", "supabase-kong"],
            db_port=5432,
            db_handoff_recovered=False,
            startup_budget=_SupabaseStartupBudget.start({}, clock=lambda: 0.0),
            stage_events=stage_events,
        )

        self.assertIsNone(result)
        self.assertEqual(stage_events[-1]["stage"], "supabase.db.probe")
        self.assertEqual(stage_events[-1]["reason"], "ready")

    def test_ensure_db_ready_reports_probe_failure_without_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            compose_root = Path(tmpdir)
            compose_path = compose_root / "docker-compose.yml"
            compose_path.write_text("services:\n  supabase-db: {}\n", encoding="utf-8")
            stage_events: list[dict[str, object]] = []
            with mock.patch("envctl_engine.requirements.supabase_lifecycle.db_flow._compose_run", return_value=None):
                result = ensure_supabase_db_ready(
                    process_runner=_Runner([False, False]),
                    compose_root=compose_root,
                    compose_project_name="envctl-test-supabase",
                    compose_path=compose_path,
                    env={"ENVCTL_SUPABASE_DB_RESTART_ON_PROBE_FAILURE": "false"},
                    db_service="supabase-db",
                    graph_services=["supabase-db"],
                    db_port=5432,
                    db_handoff_recovered=False,
                    startup_budget=_SupabaseStartupBudget.start({}, clock=lambda: 0.0),
                    stage_events=stage_events,
                )

        self.assertIsNotNone(result)
        self.assertFalse(result.success)
        self.assertIn("probe timeout waiting for readiness on port 5432 after retry", result.error or "")
        self.assertEqual(stage_events[-1]["stage"], "supabase.db.probe")
        self.assertEqual(stage_events[-1]["reason"], "failed")


if __name__ == "__main__":
    unittest.main()
