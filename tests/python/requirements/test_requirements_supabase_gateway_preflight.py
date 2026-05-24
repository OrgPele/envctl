from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from envctl_engine.requirements.supabase_lifecycle.gateway_preflight import prepare_supabase_gateway_preflight
from envctl_engine.requirements.supabase_lifecycle.types import _SupabaseStartupBudget


class SupabaseGatewayPreflightTests(unittest.TestCase):
    def test_prepare_gateway_preflight_skips_when_no_mismatch_exists(self) -> None:
        stage_events: list[dict[str, object]] = []

        with mock.patch(
            "envctl_engine.requirements.supabase_lifecycle.gateway_preflight._gateway_public_port_mismatch",
            return_value=None,
        ) as mismatch_probe:
            result = prepare_supabase_gateway_preflight(
                process_runner=SimpleNamespace(),
                compose_root=Path("/repo/supabase"),
                compose_project_name="envctl-test-supabase",
                compose_path=Path("/repo/supabase/docker-compose.yml"),
                env={},
                secondary_services=["supabase-auth", "supabase-kong"],
                gateway_service="supabase-kong",
                resolved_public_port=54321,
                startup_budget=_SupabaseStartupBudget.start({}, clock=lambda: 0.0),
                stage_events=stage_events,
            )

        self.assertIsNone(result)
        self.assertEqual(stage_events, [])
        mismatch_probe.assert_called_once()

    def test_prepare_gateway_preflight_reports_remove_failure_with_stage_event(self) -> None:
        stage_events: list[dict[str, object]] = []

        with (
            mock.patch(
                "envctl_engine.requirements.supabase_lifecycle.gateway_preflight._gateway_public_port_mismatch",
                return_value={"published": "0.0.0.0:54349"},
            ),
            mock.patch(
                "envctl_engine.requirements.supabase_lifecycle.gateway_preflight._format_gateway_port_mismatch",
                return_value="published=54349 expected=54321",
            ),
            mock.patch(
                "envctl_engine.requirements.supabase_lifecycle.gateway_preflight._remove_auth_gateway_services",
                return_value="docker rm failed",
            ) as remove_services,
        ):
            result = prepare_supabase_gateway_preflight(
                process_runner=SimpleNamespace(),
                compose_root=Path("/repo/supabase"),
                compose_project_name="envctl-test-supabase",
                compose_path=Path("/repo/supabase/docker-compose.yml"),
                env={},
                secondary_services=["supabase-auth", "supabase-kong"],
                gateway_service="supabase-kong",
                resolved_public_port=54321,
                startup_budget=_SupabaseStartupBudget.start({}, clock=lambda: 0.0),
                stage_events=stage_events,
            )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertFalse(result.success)
        self.assertEqual(result.container_name, "envctl-test-supabase")
        self.assertEqual(
            result.error,
            "failed removing stale Supabase Auth/Kong before startup: docker rm failed",
        )
        self.assertEqual(stage_events[-1]["stage"], "supabase.gateway.port_mismatch.preflight")
        self.assertEqual(stage_events[-1]["reason"], "remove_stale")
        self.assertEqual(stage_events[-1]["detail"], "published=54349 expected=54321")
        remove_services.assert_called_once()


if __name__ == "__main__":
    unittest.main()
