from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.runtime.lifecycle_requirement_ports import (
    component_port_values,
    release_requirement_ports,
    requirement_key_for_project,
    requirement_port_values,
)
from envctl_engine.state.models import RequirementsResult, RunState


class LifecycleRequirementPortsTests(unittest.TestCase):
    def test_requirement_key_for_project_matches_case_insensitive_key(self) -> None:
        state = RunState(run_id="run-1", mode="main", requirements={"Main": RequirementsResult(project="Main")})

        self.assertEqual(requirement_key_for_project(state, "main"), "Main")
        self.assertIsNone(requirement_key_for_project(state, " "))
        self.assertIsNone(requirement_key_for_project(state, "missing"))

    def test_requirement_port_values_returns_enabled_internal_final_ports_only(self) -> None:
        requirements = RequirementsResult(
            project="Main",
            db={"enabled": True, "final": 5432},
            redis={"enabled": False, "final": 6379},
            supabase={"enabled": True, "external": True, "final": 54321},
            n8n={"enabled": True, "final": 5678, "resources": {"ignored": 15678}},
        )

        self.assertEqual(requirement_port_values(requirements), {5432, 5678})

    def test_component_port_values_collects_final_and_resource_ports(self) -> None:
        self.assertEqual(
            component_port_values({"final": 5432, "resources": {"shadow": 15432, "duplicate": 5432, "zero": 0}}),
            {5432, 15432},
        )

    def test_release_requirement_ports_uses_runtime_port_planner_in_sorted_order(self) -> None:
        released: list[int] = []
        runtime = SimpleNamespace(port_planner=SimpleNamespace(release=lambda port: released.append(port)))
        requirements = RequirementsResult(
            project="Main",
            db={"enabled": True, "final": 5432},
            n8n={"enabled": True, "final": 5678},
        )

        release_requirement_ports(runtime, requirements)

        self.assertEqual(released, [5432, 5678])


if __name__ == "__main__":
    unittest.main()
