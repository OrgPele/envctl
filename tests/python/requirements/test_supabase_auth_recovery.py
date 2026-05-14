from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from envctl_engine.requirements.supabase import start_supabase_stack
from tests.python.requirements.supabase_fakes import SupabaseFakeRunner


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
