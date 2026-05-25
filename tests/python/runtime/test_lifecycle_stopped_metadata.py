from __future__ import annotations

import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.lifecycle_stopped_metadata import (
    has_dashboard_stopped_services,
    project_name_from_stopped_service,
    project_root_from_stopped_service,
    remember_dashboard_stopped_services,
    service_type_from_stopped_service,
    should_preserve_stopped_dashboard_state,
)
from envctl_engine.state.models import RunState, ServiceRecord


class LifecycleStoppedMetadataTests(unittest.TestCase):
    def test_preserve_state_only_for_interactive_preserve_or_explicit_service_stop(self) -> None:
        self.assertTrue(
            should_preserve_stopped_dashboard_state(
                Route(command="stop", mode="main", flags={"interactive_command": True})
            )
        )
        self.assertTrue(
            should_preserve_stopped_dashboard_state(
                Route(command="stop", mode="main", flags={"stop_preserve_requirements": True})
            )
        )
        self.assertTrue(
            should_preserve_stopped_dashboard_state(
                Route(command="stop", mode="main", flags={"services": ["Main Backend"]})
            )
        )
        self.assertFalse(should_preserve_stopped_dashboard_state(Route(command="stop", mode="main")))
        self.assertFalse(
            should_preserve_stopped_dashboard_state(Route(command="stop", mode="main", flags={"services": [" "]}))
        )

    def test_remember_stopped_services_merges_existing_metadata_and_project_roots(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Voice Runtime": ServiceRecord(
                    name="Main Voice Runtime",
                    type="",
                    service_slug="voice-runtime",
                    cwd="/repo/main/voice-runtime",
                    pid=2,
                    project="Main",
                ),
                "Aux Backend": ServiceRecord(
                    name="Aux Backend",
                    type="backend",
                    cwd="/repo/aux/backend",
                    pid=3,
                ),
            },
            metadata={
                "dashboard_stopped_services": [
                    {"name": "Main Frontend", "project": "Main", "type": "frontend"},
                    {"name": "", "project": "Ignored", "type": "backend"},
                ],
                "dashboard_configured_service_types": ["frontend"],
                "project_roots": {"Main": "/repo/main"},
            },
        )

        remember_dashboard_stopped_services(
            state,
            {"Main Voice Runtime", "Aux Backend", "Missing Service"},
            project_name_from_service_fn=lambda name: "Aux" if name == "Aux Backend" else "",
        )

        self.assertEqual(
            state.metadata["dashboard_stopped_services"],
            [
                {"name": "Aux Backend", "project": "Aux", "type": "backend"},
                {"name": "Main Frontend", "project": "Main", "type": "frontend"},
                {"name": "Main Voice Runtime", "project": "Main", "type": "voice-runtime"},
            ],
        )
        self.assertEqual(state.metadata["dashboard_configured_service_types"], ["backend", "frontend", "voice-runtime"])
        self.assertEqual(state.metadata["project_roots"], {"Aux": "/repo/aux", "Main": "/repo/main"})

    def test_metadata_helpers_fallback_from_service_name_and_cwd(self) -> None:
        service = ServiceRecord(name="Main Frontend", type="", cwd="/repo/main/frontend", pid=1)
        self.assertEqual(project_name_from_stopped_service("Main Frontend"), "Main")
        self.assertEqual(service_type_from_stopped_service("Main Frontend", service), "frontend")
        self.assertEqual(project_root_from_stopped_service(service, service_type="frontend"), "/repo/main")
        self.assertTrue(
            has_dashboard_stopped_services(
                RunState(
                    run_id="run-1",
                    mode="main",
                    metadata={"dashboard_stopped_services": [{"name": "Main Frontend"}]},
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
