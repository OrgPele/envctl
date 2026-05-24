from __future__ import annotations

import unittest
from unittest import mock

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RequirementsResult, RunState
from envctl_engine.ui.dashboard.stop_scope_support import (
    apply_stop_resource_tokens,
    stop_dependencies_by_project,
    stop_project_order,
    stop_route_has_explicit_scope,
    stop_service_detail,
    stop_service_type,
    stop_services_by_project,
)


def _make_state(**kwargs: object) -> RunState:
    defaults = {
        "run_id": "r1",
        "mode": "dev",
        "services": {},
        "requirements": {},
        "metadata": {},
    }
    defaults.update(kwargs)
    return RunState(**defaults)  # type: ignore[arg-type]


def _make_route(**kwargs: object) -> Route:
    defaults: dict[str, object] = {"command": "stop", "mode": "dev", "raw_args": [], "passthrough_args": [], "projects": [], "flags": {}}
    defaults.update(kwargs)
    return Route(**defaults)  # type: ignore[arg-type]


class StopScopeSupportTests(unittest.TestCase):
    def test_stop_route_has_explicit_scope_runtime_scope_flag(self) -> None:
        route = _make_route(flags={"runtime_scope": "entire-system"})
        self.assertTrue(stop_route_has_explicit_scope(route, mock.MagicMock()))

    def test_stop_route_has_explicit_scope_no_flag(self) -> None:
        route = _make_route(flags={})
        self.assertFalse(stop_route_has_explicit_scope(route, mock.MagicMock()))

    def test_stop_services_by_project_empty(self) -> None:
        state = _make_state()
        runtime = mock.MagicMock()
        runtime._project_name_from_service.return_value = None
        result = stop_services_by_project(state, runtime)
        self.assertEqual(result, {})

    def test_stop_dependencies_by_project_empty(self) -> None:
        state = _make_state()
        result = stop_dependencies_by_project(state)
        self.assertEqual(result, {})

    def test_stop_project_order_empty(self) -> None:
        state = _make_state()
        result = stop_project_order(state, mock.MagicMock(), project_names_from_state_fn=lambda s, r: [])
        self.assertEqual(result, [])

    def test_stop_service_type_backend_suffix(self) -> None:
        self.assertEqual(stop_service_type("app backend", None), "backend")

    def test_stop_service_type_frontend_suffix(self) -> None:
        self.assertEqual(stop_service_type("app frontend", None), "frontend")

    def test_stop_service_type_unknown(self) -> None:
        self.assertEqual(stop_service_type("random", None), "")

    def test_stop_service_detail_trims_suffix(self) -> None:
        self.assertEqual(stop_service_detail("app Backend", "backend"), "app")

    def test_stop_service_detail_no_suffix(self) -> None:
        self.assertEqual(stop_service_detail("app", "backend"), "app")

    def test_apply_stop_resource_tokens_empty(self) -> None:
        route = _make_route(flags={"other": True})
        state = _make_state()
        apply_stop_resource_tokens(route, state, mock.MagicMock(), [])
        self.assertNotIn("services", route.flags)

    def test_apply_stop_resource_tokens_ignores_unknown_service_token(self) -> None:
        route = _make_route(flags={"services": ["old"], "backend": True, "other": True})
        state = _make_state()
        apply_stop_resource_tokens(route, state, mock.MagicMock(), ["__STOP__:service:missing"])

        self.assertEqual(route.flags, {"other": True})

    def test_apply_stop_resource_tokens_entire_system_when_all_services_and_dependencies_selected(self) -> None:
        route = _make_route(flags={"services": ["old"], "frontend": True})
        state = _make_state(
            services={"Main Backend": object()},
            requirements={"Main": RequirementsResult(project="Main", db={"enabled": True})},
        )
        runtime = mock.MagicMock()
        runtime._project_name_from_service.return_value = "Main"

        apply_stop_resource_tokens(route, state, runtime, ["__STOP__:worktree:Main"])

        self.assertEqual(route.flags, {"runtime_scope": "entire-system"})


if __name__ == "__main__":
    unittest.main()
