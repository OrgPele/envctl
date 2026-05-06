from __future__ import annotations

import unittest

from envctl_engine.dashboard_metadata import (
    DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY,
    dashboard_configured_missing_services_by_project,
    dashboard_project_configured_services_from_metadata,
    normalize_dashboard_service_types,
    serialize_dashboard_project_configured_services,
)


class DashboardMetadataTests(unittest.TestCase):
    def test_normalize_dashboard_service_types_filters_normalizes_deduplicates_and_sorts(self) -> None:
        self.assertEqual(
            normalize_dashboard_service_types([" Frontend ", "backend", "BACKEND", "worker", ""]),
            ["backend", "frontend", "worker"],
        )

    def test_normalize_dashboard_service_types_returns_empty_for_malformed_or_unsupported_inputs(self) -> None:
        self.assertEqual(normalize_dashboard_service_types("backend"), [])
        self.assertEqual(normalize_dashboard_service_types(["worker", "api", ""]), ["api", "worker"])
        self.assertEqual(normalize_dashboard_service_types(None), [])

    def test_dashboard_project_configured_services_from_metadata_ignores_malformed_entries(self) -> None:
        metadata: dict[str, object] = {
            DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY: {
                " Main ": [" Backend ", "frontend", "worker"],
                " ": ["backend"],
                "Empty": ["worker"],
                "Malformed": "backend",
            }
        }

        self.assertEqual(
            dashboard_project_configured_services_from_metadata(metadata),
            {"Main": {"backend", "frontend", "worker"}, "Empty": {"worker"}},
        )

    def test_dashboard_project_configured_services_from_metadata_returns_empty_for_missing_or_malformed_contract(self) -> None:
        self.assertEqual(dashboard_project_configured_services_from_metadata({}), {})
        self.assertEqual(
            dashboard_project_configured_services_from_metadata({DASHBOARD_PROJECT_CONFIGURED_SERVICES_KEY: []}),
            {},
        )

    def test_serialize_dashboard_project_configured_services_normalizes_and_sorts_projects(self) -> None:
        self.assertEqual(
            serialize_dashboard_project_configured_services(
                {
                    "zeta": ["frontend", "backend", "frontend"],
                    " Alpha ": [" Frontend "],
                    " ": ["backend"],
                    "empty": ["worker"],
                }
            ),
            {"Alpha": ["frontend"], "empty": ["worker"], "zeta": ["backend", "frontend"]},
        )

    def test_dashboard_configured_missing_services_by_project_excludes_active_and_stopped_services(self) -> None:
        self.assertEqual(
            dashboard_configured_missing_services_by_project(
                configured_services={
                    "Main": {"backend", "frontend", "voice-runtime"},
                    "Feature": {"backend", "frontend", "webhook-relay"},
                },
                stopped_services={"Main": {"backend": "Main Backend"}},
                active_service_names={"Main Frontend", "Main Voice Runtime", "Feature Backend"},
            ),
            {"Feature": {"frontend", "webhook-relay"}},
        )


if __name__ == "__main__":
    unittest.main()
