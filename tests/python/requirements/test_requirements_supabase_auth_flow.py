from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from envctl_engine.requirements.supabase_lifecycle.auth_flow import complete_supabase_auth_startup
from envctl_engine.requirements.supabase_lifecycle.types import _SupabaseStartupBudget


class SupabaseAuthFlowTests(unittest.TestCase):
    def test_complete_auth_startup_records_final_ready_probe(self) -> None:
        stage_events: list[dict[str, object]] = []
        probe_attempts: list[dict[str, object]] = []
        startup_budget = _SupabaseStartupBudget.start({}, clock=lambda: 0.0)
        probe = SimpleNamespace(ready=True, attempts=[{"action": "initial_probe"}], last_error="")

        with mock.patch(
            "envctl_engine.requirements.supabase_lifecycle.auth_flow._probe_supabase_auth_health_with_attempts",
            return_value=probe,
        ):
            result = complete_supabase_auth_startup(
                process_runner=SimpleNamespace(),
                compose_root=Path("/repo/supabase"),
                compose_project_name="envctl-test-supabase",
                compose_path=Path("/repo/supabase/docker-compose.yml"),
                env={},
                secondary_services=["supabase-auth", "supabase-kong"],
                gateway_service=None,
                resolved_public_port=54321,
                startup_budget=startup_budget,
                stage_events=stage_events,
                probe_attempts=probe_attempts,
            )

        self.assertTrue(result.success)
        self.assertEqual(result.container_name, "envctl-test-supabase")
        self.assertEqual(result.probe_attempt_count, 1)
        self.assertEqual(probe_attempts, [{"action": "initial_probe"}])
        self.assertEqual(stage_events[-1]["stage"], "supabase.auth.probe.final")
        self.assertEqual(stage_events[-1]["reason"], "ready")


if __name__ == "__main__":
    unittest.main()
