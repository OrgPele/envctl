from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.restart_prestop_support import (
    restart_fallback_start_route,
    restart_port_assignments,
    restart_prestop_preservation,
    restart_start_route,
)


class RestartPrestopSupportTests(unittest.TestCase):
    def test_restart_fallback_start_route_preserves_request_context_and_marks_restart(self) -> None:
        route = Route(
            command="restart",
            mode="trees",
            raw_args=["restart", "--project", "Feature"],
            passthrough_args=["--", "extra"],
            projects=["Feature"],
            flags={"runtime_scope": "backend"},
        )

        updated = restart_fallback_start_route(route, restart_lookup_mode="trees")

        self.assertEqual(updated.command, "start")
        self.assertEqual(updated.mode, "trees")
        self.assertEqual(updated.raw_args, route.raw_args)
        self.assertEqual(updated.passthrough_args, route.passthrough_args)
        self.assertEqual(updated.projects, ["Feature"])
        self.assertEqual(updated.flags["runtime_scope"], "backend")
        self.assertTrue(updated.flags["_restart_request"])

    def test_restart_start_route_records_sorted_selection_policy(self) -> None:
        route = Route(command="restart", mode="main", raw_args=["restart"], flags={"force": True})

        updated = restart_start_route(
            route,
            restart_lookup_mode="main",
            selected_services={"Main Frontend", "Main Backend"},
            target_projects={"Main"},
            include_requirements=False,
        )

        self.assertEqual(updated.command, "start")
        self.assertEqual(updated.flags["_restart_selected_services"], ["Main Backend", "Main Frontend"])
        self.assertEqual(updated.flags["_restart_target_projects"], ["Main"])
        self.assertFalse(updated.flags["_restart_include_requirements"])
        self.assertTrue(updated.flags["_restart_request"])
        self.assertTrue(updated.flags["force"])

    def test_restart_prestop_preservation_splits_services_and_requirements(self) -> None:
        state = SimpleNamespace(
            services={
                "Main Backend": object(),
                "Main Frontend": object(),
                "Other Backend": object(),
            },
            requirements={
                "Main": SimpleNamespace(name="main requirements"),
                "Other": SimpleNamespace(name="other requirements"),
            },
        )

        result = restart_prestop_preservation(
            state,
            selected_services={"Main Backend", "Main Frontend"},
            include_requirements=True,
            target_projects={"Main"},
        )

        self.assertEqual(set(result.preserved_services), {"Other Backend"})
        self.assertEqual(set(result.requirements_to_release), {"Main"})
        self.assertEqual(set(result.preserved_requirements), {"Other"})

    def test_restart_prestop_preservation_preserves_requirements_when_not_included(self) -> None:
        state = SimpleNamespace(
            services={"Main Backend": object()},
            requirements={"Main": object()},
        )

        result = restart_prestop_preservation(
            state,
            selected_services={"Main Backend"},
            include_requirements=False,
            target_projects={"Main"},
        )

        self.assertEqual(result.preserved_services, {})
        self.assertEqual(result.requirements_to_release, {})
        self.assertEqual(set(result.preserved_requirements), {"Main"})

    def test_restart_port_assignments_use_actual_port_then_requested_port_for_selected_services(self) -> None:
        state = SimpleNamespace(
            services={
                "Main Backend": SimpleNamespace(
                    name="Main Backend",
                    project="Main",
                    type="backend",
                    actual_port=8001,
                    requested_port=8000,
                ),
                "Main Frontend": SimpleNamespace(
                    name="Main Frontend",
                    project="Main",
                    type="frontend",
                    actual_port=None,
                    requested_port=3000,
                ),
                "Other Backend": SimpleNamespace(
                    name="Other Backend",
                    project="Other",
                    type="backend",
                    actual_port=8100,
                    requested_port=8100,
                ),
            }
        )

        self.assertEqual(
            restart_port_assignments(
                state,
                selected_services={"Main Backend", "Main Frontend"},
                project_name_from_service=lambda name: str(name).removesuffix(" Backend").removesuffix(" Frontend"),
            ),
            {"main": {"backend": 8001, "frontend": 3000}},
        )

    def test_restart_port_assignments_uses_project_name_fallback_and_ignores_invalid_ports(self) -> None:
        state = SimpleNamespace(
            services={
                "Fallback Backend": SimpleNamespace(
                    name="Fallback Backend",
                    project="",
                    type="backend",
                    actual_port=0,
                    requested_port=8000,
                ),
                "Fallback Frontend": SimpleNamespace(
                    name="Fallback Frontend",
                    project="",
                    type="frontend",
                    actual_port=-1,
                    requested_port=None,
                ),
            }
        )

        self.assertEqual(
            restart_port_assignments(
                state,
                selected_services={"Fallback Backend", "Fallback Frontend"},
                project_name_from_service=lambda name: str(name).removesuffix(" Backend").removesuffix(" Frontend"),
            ),
            {"fallback": {"backend": 8000}},
        )


if __name__ == "__main__":
    unittest.main()
