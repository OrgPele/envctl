from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest import mock

from envctl_engine.requirements.supabase_lifecycle.service_resolution import resolve_supabase_startup_services


class SupabaseServiceResolutionTests(unittest.TestCase):
    def test_resolve_startup_services_prefers_known_aliases(self) -> None:
        with mock.patch(
            "envctl_engine.requirements.supabase_lifecycle.service_resolution._compose_service_list",
            return_value=["db", "gotrue", "gateway"],
        ) as list_services:
            services = resolve_supabase_startup_services(
                process_runner=SimpleNamespace(),
                compose_root=Path("/repo/supabase"),
                compose_project_name="envctl-test-supabase",
                compose_path=Path("/repo/supabase/docker-compose.yml"),
                env={},
            )

        self.assertEqual(services.db_service, "db")
        self.assertEqual(services.auth_service, "gotrue")
        self.assertEqual(services.gateway_service, "gateway")
        self.assertEqual(services.secondary_services, ["gotrue", "gateway"])
        self.assertEqual(services.graph_services, ["db", "gotrue", "gateway"])
        list_services.assert_called_once()

    def test_resolve_startup_services_defaults_db_and_omits_missing_secondaries(self) -> None:
        with mock.patch(
            "envctl_engine.requirements.supabase_lifecycle.service_resolution._compose_service_list",
            return_value=["analytics"],
        ):
            services = resolve_supabase_startup_services(
                process_runner=SimpleNamespace(),
                compose_root=Path("/repo/supabase"),
                compose_project_name="envctl-test-supabase",
                compose_path=Path("/repo/supabase/docker-compose.yml"),
                env={},
            )

        self.assertEqual(services.db_service, "supabase-db")
        self.assertIsNone(services.auth_service)
        self.assertIsNone(services.gateway_service)
        self.assertEqual(services.secondary_services, [])
        self.assertEqual(services.graph_services, ["supabase-db"])


if __name__ == "__main__":
    unittest.main()
