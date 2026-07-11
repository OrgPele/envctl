from __future__ import annotations

import unittest
from pathlib import Path
import tempfile
from types import SimpleNamespace

from envctl_engine.runtime.command_router import Route
from envctl_engine.runtime.lifecycle_dependency_stop import (
    release_requirement_component_ports,
    release_selected_dependency_components,
    requirements_have_enabled_components,
    select_dependency_components_for_stop,
)
from envctl_engine.runtime.lifecycle_requirement_ports import requirement_component_port_owners
from envctl_engine.shared.ports import PortPlanner
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
            release_component_ports_fn=lambda _requirements, _dependency_id, component: (
                release_requirement_component_ports(
                    component,
                    port_planner=SimpleNamespace(release=released.append),
                )
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
            release_component_ports_fn=lambda _requirements, _dependency_id, component: (
                release_requirement_component_ports(
                    component,
                    port_planner=SimpleNamespace(release=released.append),
                )
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
            port_planner=SimpleNamespace(release=released.append),
        )

        self.assertEqual(released, [5432, 15432])

    def test_selected_dependency_stop_releases_exact_prior_session_owner(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            prior = PortPlanner(
                lock_dir=tmpdir,
                session_id="prior-session",
                availability_checker=lambda _port: True,
            )
            current = PortPlanner(
                lock_dir=tmpdir,
                session_id="current-session",
                availability_checker=lambda _port: True,
            )
            prior.reserve_next(5432, owner="Main:db")
            requirements = RequirementsResult(
                project="Main",
                db={
                    "enabled": True,
                    "final": 5432,
                    "port_lock_session": "prior-session",
                },
                redis={"enabled": True, "final": 6379},
            )
            state = RunState(
                run_id="run-prior",
                mode="main",
                requirements={"Main": requirements},
            )

            release_selected_dependency_components(
                state,
                {"Main": {"postgres"}},
                release_component_ports_fn=lambda owner, dependency_id, component: release_requirement_component_ports(
                    component,
                    port_planner=current,
                    owner_candidates=requirement_component_port_owners(owner, dependency_id),
                ),
            )

            self.assertEqual(list(Path(tmpdir).glob("*.lock")), [])
            self.assertFalse(requirements.db.get("enabled", False))
            self.assertTrue(requirements.redis.get("enabled", False))


if __name__ == "__main__":
    unittest.main()
