from __future__ import annotations

import unittest

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.lifecycle_dependency_stop import (
    release_requirement_component_ports,
    release_selected_dependency_components,
    requirements_have_enabled_components,
    select_dependency_components_for_stop,
)
from envctl_engine.state.models import RequirementsResult, RunState


class LifecycleDependencyStopTests(unittest.TestCase):
    def test_select_dependency_components_filters_unknown_projects_dependencies_and_disabled_components(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            requirements={
                "Main": RequirementsResult(project="Main", db={"enabled": True}, redis={"enabled": False}),
                "Aux": RequirementsResult(project="Aux", redis={"enabled": True}),
            },
        )
        route = Route(
            command="stop",
            mode="main",
            flags={
                "stop_dependency_components": [
                    "main:postgres",
                    "MAIN:redis",
                    "aux:redis",
                    "missing:redis",
                    "Main:unknown",
                    "invalid-token",
                ]
            },
        )

        self.assertEqual(
            select_dependency_components_for_stop(state, route),
            {"Aux": {"redis"}, "Main": {"postgres"}},
        )

    def test_release_selected_dependency_components_releases_internal_ports_and_prunes_empty_projects(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    db={"enabled": True, "final": 5432, "resources": {"shadow": 15432}},
                    redis={"enabled": True, "final": 6379, "external": True},
                ),
                "Aux": RequirementsResult(project="Aux", db={"enabled": True, "final": 6543}),
            },
        )
        released: list[int] = []

        release_selected_dependency_components(
            state,
            {"Main": {"postgres", "redis"}, "Aux": {"postgres"}},
            release_component_ports_fn=lambda component: release_requirement_component_ports(
                component,
                release_port_fn=released.append,
            ),
        )

        self.assertEqual(released, [5432, 15432, 6543])
        self.assertEqual(state.requirements, {})

    def test_release_selected_dependency_components_preserves_projects_with_enabled_components(self) -> None:
        state = RunState(
            run_id="run-1",
            mode="main",
            requirements={
                "Main": RequirementsResult(
                    project="Main",
                    db={"enabled": True, "final": 5432},
                    redis={"enabled": True, "final": 6379},
                ),
            },
        )
        released: list[int] = []

        release_selected_dependency_components(
            state,
            {"Main": {"redis"}},
            release_component_ports_fn=lambda component: release_requirement_component_ports(
                component,
                release_port_fn=released.append,
            ),
        )

        self.assertEqual(released, [6379])
        self.assertIn("Main", state.requirements)
        self.assertTrue(state.requirements["Main"].db.get("enabled", False))
        self.assertFalse(state.requirements["Main"].redis.get("enabled", False))
        self.assertTrue(requirements_have_enabled_components(state.requirements["Main"]))

    def test_release_requirement_component_ports_dedupes_positive_final_and_resource_ports(self) -> None:
        released: list[int] = []

        release_requirement_component_ports(
            {"final": 5432, "resources": {"shadow": 15432, "duplicate": 5432, "ignored": 0}},
            release_port_fn=released.append,
        )

        self.assertEqual(released, [5432, 15432])


if __name__ == "__main__":
    unittest.main()
