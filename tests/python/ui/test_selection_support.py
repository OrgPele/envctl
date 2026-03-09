from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.ui.selection_support import (
    interactive_selection_allowed,
    no_target_selected_message,
    project_names_from_state,
    route_has_explicit_target,
    services_from_selection,
    service_types_from_service_names,
)
from envctl_engine.ui.selection_types import TargetSelection


def _route(**overrides: object) -> Route:
    payload = {
        "command": "restart",
        "mode": "main",
        "raw_args": [],
        "passthrough_args": [],
        "projects": [],
        "flags": {},
    }
    payload.update(overrides)
    return Route(**payload)


def _state() -> RunState:
    return RunState(
        run_id="run-1",
        mode="main",
        services={
            "Main Backend": ServiceRecord(name="Main Backend", type="backend", cwd="/tmp/main"),
            "Main Frontend": ServiceRecord(name="Main Frontend", type="frontend", cwd="/tmp/main"),
            "Admin Backend": ServiceRecord(name="Admin Backend", type="backend", cwd="/tmp/admin"),
        },
    )


class SelectionSupportTests(unittest.TestCase):
    def test_interactive_selection_allowed_respects_tty_batch_and_dashboard_override(self) -> None:
        runtime = SimpleNamespace(_batch_mode_requested=lambda route: bool(route.flags.get("batch")))

        with patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=False):
            self.assertFalse(interactive_selection_allowed(runtime, _route()))

        with patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True):
            self.assertFalse(interactive_selection_allowed(runtime, _route(flags={"batch": True})))
            self.assertTrue(
                interactive_selection_allowed(
                    runtime,
                    _route(flags={"batch": True, "interactive_command": True}),
                    allow_dashboard_override=True,
                )
            )

    def test_project_names_from_state_preserves_dedupe_order(self) -> None:
        runtime = SimpleNamespace(_project_name_from_service=lambda name: name.split()[0])
        names = project_names_from_state(runtime, _state())
        self.assertEqual([project.name for project in names], ["Main", "Admin"])

    def test_project_names_from_state_falls_back_to_metadata_project_roots(self) -> None:
        runtime = SimpleNamespace(_project_name_from_service=lambda _name: "")
        state = RunState(
            run_id="run-plan",
            mode="trees",
            metadata={"project_roots": {"feature-a-1": "/tmp/a", "feature-b-1": "/tmp/b"}},
        )

        names = project_names_from_state(runtime, state)

        self.assertEqual([project.name for project in names], ["feature-a-1", "feature-b-1"])

    def test_services_from_selection_handles_all_projects_and_services(self) -> None:
        runtime = SimpleNamespace(_project_name_from_service=lambda name: name.split()[0])
        state = _state()

        self.assertEqual(
            services_from_selection(runtime, TargetSelection(all_selected=True), state),
            set(state.services.keys()),
        )
        self.assertEqual(
            services_from_selection(runtime, TargetSelection(service_names=["Main Backend"]), state),
            {"Main Backend"},
        )
        self.assertEqual(
            services_from_selection(runtime, TargetSelection(project_names=["main"]), state),
            {"Main Backend", "Main Frontend"},
        )

    def test_no_target_selected_message_and_explicit_target_detection_match_route_context(self) -> None:
        runtime = SimpleNamespace(_selectors_from_passthrough=lambda args: {"svc"} if args else set())

        self.assertEqual(
            no_target_selected_message("logs", route=None, interactive_allowed=True),
            "No log target selected.",
        )
        self.assertIn(
            "--project <name>",
            no_target_selected_message("restart", route=_route(mode="trees"), interactive_allowed=False),
        )

        self.assertTrue(route_has_explicit_target(_route(flags={"all": True}), runtime))
        self.assertTrue(route_has_explicit_target(_route(projects=["Main"]), runtime))
        self.assertTrue(route_has_explicit_target(_route(flags={"services": ["Main Backend"]}), runtime))
        self.assertTrue(route_has_explicit_target(_route(passthrough_args=["selector"]), runtime))
        self.assertFalse(route_has_explicit_target(_route(), runtime))

    def test_service_types_from_service_names_infers_backend_and_frontend(self) -> None:
        self.assertEqual(
            service_types_from_service_names(["Main Backend", "Admin Frontend", "Worker"]),
            {"backend", "frontend"},
        )


if __name__ == "__main__":
    unittest.main()
