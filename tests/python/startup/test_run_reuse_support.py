from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.run_reuse_support import (
    dashboard_stopped_service_entries,
    fresh_start_replacement_services,
    metadata_without_dashboard_stopped_services,
    run_reuse_debug_orch_groups,
)


class RunReuseSupportTests(unittest.TestCase):
    def test_run_reuse_debug_orch_groups_only_apply_to_plan_commands(self) -> None:
        runtime = SimpleNamespace(env={"ENVCTL_DEBUG_PLAN_ORCH_GROUP": "alpha+ beta,gamma ,,"})

        self.assertEqual(run_reuse_debug_orch_groups(runtime, requested_command="plan"), {"alpha", "beta", "gamma"})
        self.assertEqual(run_reuse_debug_orch_groups(runtime, requested_command="start"), set())

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

    def test_fresh_start_replacement_services_selects_configured_service_types_for_target_projects(self) -> None:
        route = Route(command="start", mode="main", raw_args=["start"], flags={})
        candidate_state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(name="Main Backend", project="Main", type="backend"),
                "Main Frontend": SimpleNamespace(name="Main Frontend", project="Main", type="frontend"),
                "Other Backend": SimpleNamespace(name="Other Backend", project="Other", type="backend"),
            }
        )

        self.assertEqual(
            fresh_start_replacement_services(
                route=route,
                selected_contexts=[SimpleNamespace(name="Main")],
                candidate_state=candidate_state,
                configured_service_types={"backend"},
                additional_services=(),
                project_name_from_service=lambda name: str(name).removesuffix(" Backend").removesuffix(" Frontend"),
            ),
            {"Main Backend"},
        )

    def test_fresh_start_replacement_services_honors_restart_service_type_filters(self) -> None:
        route = Route(
            command="restart",
            mode="main",
            raw_args=["restart"],
            flags={"_restart_request": True, "restart_service_types": ["frontend"]},
        )
        candidate_state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(name="Main Backend", project="Main", type="backend"),
                "Main Frontend": SimpleNamespace(name="Main Frontend", project="Main", type="frontend"),
            }
        )

        self.assertEqual(
            fresh_start_replacement_services(
                route=route,
                selected_contexts=[SimpleNamespace(name="Main")],
                candidate_state=candidate_state,
                configured_service_types={"backend", "frontend"},
                additional_services=(),
                project_name_from_service=lambda name: str(name).removesuffix(" Backend").removesuffix(" Frontend"),
            ),
            {"Main Frontend"},
        )


if __name__ == "__main__":
    unittest.main()
