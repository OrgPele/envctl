from __future__ import annotations

import unittest
from unittest import mock

from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard.restart_selection_support import (
    apply_restart_resource_tokens,
    dashboard_project_configured_services,
    dashboard_stopped_services_by_project,
    has_dashboard_stopped_services,
    has_restartable_inactive_services,
    restart_project_order,
)


def _make_state(**kwargs: object) -> RunState:
    defaults = {"run_id": "r1", "mode": "dev", "services": {}, "requirements": {}, "metadata": {}}
    defaults.update(kwargs)
    return RunState(**defaults)  # type: ignore[arg-type]


class RestartSelectionSupportTests(unittest.TestCase):
    def test_dashboard_stopped_services_by_project_empty(self) -> None:
        state = _make_state()
        result = dashboard_stopped_services_by_project(state)
        self.assertEqual(result, {})

    def test_dashboard_stopped_services_by_project_with_data(self) -> None:
        state = _make_state(metadata={
            "dashboard_stopped_services": [
                {"project": "p1", "type": "backend", "name": "p1 Backend"},
                {"project": "p1", "type": "frontend", "name": "p1 Frontend"},
            ]
        })
        result = dashboard_stopped_services_by_project(state)
        self.assertEqual(result, {"p1": {"backend": "p1 Backend", "frontend": "p1 Frontend"}})

    def test_dashboard_project_configured_services_empty(self) -> None:
        state = _make_state()
        result = dashboard_project_configured_services(state)
        self.assertEqual(result, {})

    def test_has_dashboard_stopped_services_false(self) -> None:
        state = _make_state()
        self.assertFalse(has_dashboard_stopped_services(state, dashboard_stopped_services_by_project_fn=dashboard_stopped_services_by_project))

    def test_has_dashboard_stopped_services_true(self) -> None:
        state = _make_state(metadata={"dashboard_stopped_services": [{"project": "p1", "type": "backend", "name": "svc"}]})
        self.assertTrue(has_dashboard_stopped_services(state, dashboard_stopped_services_by_project_fn=dashboard_stopped_services_by_project))

    def test_has_restartable_inactive_services_false(self) -> None:
        state = _make_state()
        self.assertFalse(has_restartable_inactive_services(
            state,
            dashboard_stopped_services_by_project_fn=dashboard_stopped_services_by_project,
            dashboard_configured_missing_services_by_project_fn=lambda s: {},
        ))

    def test_restart_project_order_empty(self) -> None:
        state = _make_state()
        result = restart_project_order(
            state, mock.MagicMock(),
            stop_project_order_fn=lambda s, r: [],
            dashboard_stopped_services_by_project_fn=lambda s: {},
            dashboard_project_configured_services_fn=lambda s: {},
        )
        self.assertEqual(result, [])

    def test_apply_restart_resource_tokens_worktree(self) -> None:
        from envctl_engine.runtime.command_router import Route
        route = Route(command="restart", mode="dev", raw_args=[], passthrough_args=[], projects=[], flags={"all": True})
        state = _make_state()
        apply_restart_resource_tokens(route, state, mock.MagicMock(), ["__RESTART__:worktree:p1"])
        self.assertIn("services", route.flags)


if __name__ == "__main__":
    unittest.main()
