from __future__ import annotations

import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.lifecycle_service_stop_selection import (
    select_services_for_stop,
    service_matches_runtime_scope,
)
from envctl_engine.state.models import RequirementsResult, RunState, ServiceRecord
from envctl_engine.ui.target_selector import TargetSelection


class LifecycleServiceStopSelectionTests(unittest.TestCase):
    def test_runtime_scope_selects_matching_services_without_interactive_prompt(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1),
                "Main Frontend": ServiceRecord(name="Main Frontend", type="frontend", cwd=".", pid=2),
                "Aux Backend": ServiceRecord(name="Aux Backend", type="backend", cwd=".", pid=3),
            },
        )

        selected = select_services_for_stop(
            state,
            Route(command="stop", mode="main", flags={"runtime_scope": "backend"}),
            project_name_from_service_fn=lambda name: name.split(" ", 1)[0],
            selectors_from_passthrough_fn=lambda _args: set(),
            interactive_stop_selection_fn=lambda _route, _state: self.fail("interactive prompt should not run"),
            services_from_selection_fn=lambda _selection, _state: self.fail("selection projection should not run"),
        )

        self.assertEqual(selected, {"Aux Backend", "Main Backend"})

    def test_runtime_scope_intersects_explicit_project_selector(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="trees",
            services={
                "FeatureA Backend": ServiceRecord(
                    name="FeatureA Backend",
                    type="backend",
                    cwd=".",
                    pid=1,
                    project="FeatureA",
                ),
                "FeatureB Backend": ServiceRecord(
                    name="FeatureB Backend",
                    type="backend",
                    cwd=".",
                    pid=2,
                    project="FeatureB",
                ),
            },
        )

        selected = select_services_for_stop(
            state,
            Route(
                command="stop",
                mode="trees",
                projects=["FeatureA"],
                flags={"runtime_scope": "backend"},
            ),
            project_name_from_service_fn=lambda name: name.split(" ", 1)[0],
            selectors_from_passthrough_fn=lambda _args: set(),
            interactive_stop_selection_fn=lambda _route, _state: self.fail("interactive prompt should not run"),
            services_from_selection_fn=lambda _selection, _state: self.fail("selection projection should not run"),
        )

        self.assertEqual(selected, {"FeatureA Backend"})

    def test_service_and_project_selectors_match_slug_display_name_and_passthrough_project(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            services={
                "Main Voice Runtime": ServiceRecord(
                    name="Main Voice Runtime",
                    type="voice-runtime",
                    cwd=".",
                    pid=1,
                    project="Main",
                    service_slug="voice-runtime",
                ),
                "Aux Backend": ServiceRecord(name="Aux Backend", type="backend", cwd=".", pid=2),
            },
        )
        route = Route(
            command="stop",
            mode="main",
            projects=["missing"],
            passthrough_args=["Aux"],
            flags={"services": ["Voice Runtime"]},
        )

        selected = select_services_for_stop(
            state,
            route,
            project_name_from_service_fn=lambda name: name.split(" ", 1)[0],
            selectors_from_passthrough_fn=lambda _args: {"aux"},
            interactive_stop_selection_fn=lambda _route, _state: self.fail("interactive prompt should not run"),
            services_from_selection_fn=lambda _selection, _state: self.fail("selection projection should not run"),
        )

        self.assertEqual(selected, {"Aux Backend", "Main Voice Runtime"})

    def test_selector_miss_and_dependency_component_selection_do_not_fall_back_to_all_services(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            services={"Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1)},
            requirements={"Main": RequirementsResult(project="Main", redis={"enabled": True})},
        )

        selector_miss = select_services_for_stop(
            state,
            Route(command="stop", mode="main", flags={"services": ["missing"]}),
            project_name_from_service_fn=lambda name: name.split(" ", 1)[0],
            selectors_from_passthrough_fn=lambda _args: set(),
            interactive_stop_selection_fn=lambda _route, _state: self.fail("interactive prompt should not run"),
            services_from_selection_fn=lambda _selection, _state: self.fail("selection projection should not run"),
        )
        dependency_only = select_services_for_stop(
            state,
            Route(command="stop", mode="main", flags={"stop_dependency_components": ["Main:redis"]}),
            project_name_from_service_fn=lambda name: name.split(" ", 1)[0],
            selectors_from_passthrough_fn=lambda _args: set(),
            interactive_stop_selection_fn=lambda _route, _state: self.fail("interactive prompt should not run"),
            services_from_selection_fn=lambda _selection, _state: self.fail("selection projection should not run"),
        )

        self.assertEqual(selector_miss, set())
        self.assertEqual(dependency_only, set())

    def test_interactive_selection_can_cancel_or_select_services(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            services={"Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd=".", pid=1)},
        )

        selected = select_services_for_stop(
            state,
            Route(command="stop", mode="main"),
            project_name_from_service_fn=lambda name: name.split(" ", 1)[0],
            selectors_from_passthrough_fn=lambda _args: set(),
            interactive_stop_selection_fn=lambda _route, _state: TargetSelection(service_names=["Main Backend"]),
            services_from_selection_fn=lambda selection, _state: set(getattr(selection, "service_names", [])),
        )
        cancelled = select_services_for_stop(
            state,
            Route(command="stop", mode="main"),
            project_name_from_service_fn=lambda name: name.split(" ", 1)[0],
            selectors_from_passthrough_fn=lambda _args: set(),
            interactive_stop_selection_fn=lambda _route, _state: TargetSelection(cancelled=True),
            services_from_selection_fn=lambda _selection, _state: self.fail("selection projection should not run"),
        )

        self.assertEqual(selected, {"Main Backend"})
        self.assertEqual(cancelled, set())

    def test_service_matches_runtime_scope_uses_type_and_name_suffix(self) -> None:
        self.assertTrue(
            service_matches_runtime_scope(
                "Main Worker",
                ServiceRecord(name="Main Worker", type="backend", cwd=".", pid=1),
                "backend",
            )
        )
        self.assertTrue(
            service_matches_runtime_scope(
                "Main Backend",
                ServiceRecord(name="Main Backend", type="backend-worker", cwd=".", pid=1),
                "backend",
            )
        )
        self.assertFalse(
            service_matches_runtime_scope(
                "Main Worker",
                ServiceRecord(name="Main Worker", type="backend-worker", cwd=".", pid=1),
                "frontend",
            )
        )


if __name__ == "__main__":
    unittest.main()
