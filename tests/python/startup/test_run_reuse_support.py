from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.startup.run_reuse_support import (
    dashboard_stopped_service_entries,
    metadata_without_dashboard_stopped_services,
)


class RunReuseSupportTests(unittest.TestCase):
    def test_dashboard_stopped_service_entries_normalizes_valid_backend_frontend_entries(self) -> None:
        state = SimpleNamespace(
            metadata={
                "dashboard_stopped_services": [
                    {"project": " Main ", "type": " Frontend ", "name": " Main Frontend "},
                    {"project": "Main", "type": "backend", "name": ""},
                    {"project": "", "type": "frontend", "name": "missing project"},
                    {"project": "Main", "type": "worker", "name": "Main Worker"},
                    "invalid",
                ]
            }
        )

        self.assertEqual(
            dashboard_stopped_service_entries(state),
            [
                {"project": "Main", "type": "frontend", "name": "Main Frontend"},
                {"project": "Main", "type": "backend", "name": "Main Backend"},
            ],
        )

    def test_dashboard_stopped_service_entries_ignores_missing_or_invalid_metadata(self) -> None:
        self.assertEqual(dashboard_stopped_service_entries(SimpleNamespace(metadata={})), [])
        self.assertEqual(dashboard_stopped_service_entries(SimpleNamespace(metadata={"dashboard_stopped_services": {}})), [])

    def test_metadata_without_dashboard_stopped_services_removes_restored_entries_only(self) -> None:
        metadata = {
            "keep": True,
            "dashboard_stopped_services": [
                {"name": "Main Frontend", "project": "Main", "type": "frontend"},
                {"name": "Main Backend", "project": "Main", "type": "backend"},
                "invalid",
            ],
        }

        self.assertEqual(
            metadata_without_dashboard_stopped_services(
                metadata,
                restored_service_names={"Main Frontend"},
            ),
            {
                "keep": True,
                "dashboard_stopped_services": [
                    {"name": "Main Backend", "project": "Main", "type": "backend"},
                    "invalid",
                ],
            },
        )

    def test_metadata_without_dashboard_stopped_services_drops_key_when_all_entries_restored(self) -> None:
        metadata = {
            "dashboard_stopped_services": [
                {"name": "Main Frontend", "project": "Main", "type": "frontend"},
            ],
            "keep": True,
        }

        self.assertEqual(
            metadata_without_dashboard_stopped_services(
                metadata,
                restored_service_names={"Main Frontend"},
            ),
            {"keep": True},
        )


if __name__ == "__main__":
    unittest.main()
