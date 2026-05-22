from __future__ import annotations

import unittest
from types import SimpleNamespace

from envctl_engine.runtime.command_router import Route
from envctl_engine.startup.restart_prestop_support import (
    restart_fallback_start_route,
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


if __name__ == "__main__":
    unittest.main()
