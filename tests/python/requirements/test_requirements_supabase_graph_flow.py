from __future__ import annotations

from pathlib import Path
import unittest
from unittest import mock

from envctl_engine.requirements.supabase_lifecycle.graph_flow import start_supabase_compose_graph
from envctl_engine.requirements.supabase_lifecycle.types import _SupabaseStartupBudget


class SupabaseGraphFlowTests(unittest.TestCase):
    def test_start_compose_graph_records_graph_up_success(self) -> None:
        stage_events: list[dict[str, object]] = []
        with mock.patch("envctl_engine.requirements.supabase_lifecycle.graph_flow._compose_run", return_value=None):
            failure, recovered = start_supabase_compose_graph(
                process_runner=object(),
                compose_root=Path("/repo/supabase"),
                compose_project_name="envctl-test-supabase",
                compose_path=Path("/repo/supabase/docker-compose.yml"),
                env={},
                db_service="supabase-db",
                graph_services=["supabase-db", "supabase-auth", "supabase-kong"],
                secondary_services=["supabase-auth", "supabase-kong"],
                db_port=5432,
                resolved_public_port=54321,
                startup_budget=_SupabaseStartupBudget.start({}, clock=lambda: 0.0),
                stage_events=stage_events,
            )

        self.assertIsNone(failure)
        self.assertFalse(recovered)
        self.assertEqual(stage_events[-1]["stage"], "supabase.graph.up")
        self.assertEqual(stage_events[-1]["detail"], "supabase-db,supabase-auth,supabase-kong")

    def test_start_compose_graph_records_network_recovery_marker(self) -> None:
        stage_events: list[dict[str, object]] = []
        with mock.patch(
            "envctl_engine.requirements.supabase_lifecycle.graph_flow._compose_run",
            return_value="network_recovery=compose_down_remove_orphans",
        ):
            failure, recovered = start_supabase_compose_graph(
                process_runner=object(),
                compose_root=Path("/repo/supabase"),
                compose_project_name="envctl-test-supabase",
                compose_path=Path("/repo/supabase/docker-compose.yml"),
                env={},
                db_service="supabase-db",
                graph_services=["supabase-db"],
                secondary_services=[],
                db_port=5432,
                resolved_public_port=54321,
                startup_budget=_SupabaseStartupBudget.start({}, clock=lambda: 0.0),
                stage_events=stage_events,
            )

        self.assertIsNone(failure)
        self.assertTrue(recovered)
        self.assertEqual(stage_events[-1]["stage"], "supabase.compose.network_recovery")
        self.assertEqual(stage_events[-1]["detail"], "compose_down_remove_orphans")


if __name__ == "__main__":
    unittest.main()
