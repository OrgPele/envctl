from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.dashboard.failure_detail_support import (
    ensure_short_test_summary_path,
    print_interactive_failure_details,
    print_migrate_result_details,
    print_project_action_failure_details,
    print_test_failure_details,
    failure_details_available,
    summary_display_path,
)


def _make_state(metadata: dict[str, object] | None = None) -> RunState:
    return RunState(run_id="r1", mode="dev", metadata=metadata or {})


def _make_route(command: str, **kwargs: object) -> Route:
    defaults: dict[str, object] = {"mode": "dev", "raw_args": [], "passthrough_args": [], "projects": [], "flags": {}}
    defaults.update(kwargs)
    return Route(command=command, **defaults)  # type: ignore[arg-type]


class FailureDetailSupportTests(unittest.TestCase):
    def test_ensure_short_test_summary_path_returns_original_when_missing(self) -> None:
        result = ensure_short_test_summary_path(
            project_name="p1", summary_path="/nonexistent/path/summary.txt"
        )
        self.assertEqual(result, "/nonexistent/path/summary.txt")

    def test_ensure_short_test_summary_path_returns_ft_prefix_directly(self) -> None:
        with mock.patch.object(Path, "is_file", return_value=True):
            result = ensure_short_test_summary_path(
                project_name="p1", summary_path="/runs/ft_abc123.txt"
            )
            self.assertEqual(result, "/runs/ft_abc123.txt")

    def test_summary_display_path_prefers_short_summary_path(self) -> None:
        entry: dict[str, object] = {
            "short_summary_path": "/tmp/ft_short.txt",
            "summary_path": "/tmp/long/path/summary.txt",
        }
        with mock.patch.object(Path, "is_file", return_value=True):
            result = summary_display_path(project_name="p1", entry=entry)
        self.assertEqual(result, "/tmp/ft_short.txt")

    def test_failure_details_available_no_metadata(self) -> None:
        state = _make_state()
        route = _make_route("test", projects=["p1"])
        self.assertFalse(failure_details_available(route, state, project_names_from_state_fn=lambda s: []))

    def test_print_test_failure_details_no_metadata(self) -> None:
        state = _make_state()
        route = _make_route("test", projects=["p1"])
        self.assertFalse(print_test_failure_details(route, state, runtime=mock.MagicMock(), project_names_from_state_fn=lambda s: []))

    def test_print_project_action_failure_details_no_metadata(self) -> None:
        state = _make_state()
        route = _make_route("build", projects=["p1"])
        self.assertFalse(print_project_action_failure_details(route, state, runtime=mock.MagicMock(), project_names_from_state_fn=lambda s: [], project_name_list_fn=lambda x: x))

    def test_print_migrate_result_details_no_metadata(self) -> None:
        state = _make_state()
        route = _make_route("migrate", projects=["p1"])
        self.assertFalse(print_migrate_result_details(route, state, runtime=mock.MagicMock(), project_names_from_state_fn=lambda s: [], project_name_list_fn=lambda x: x))

    def test_print_interactive_failure_details_falls_back_to_exit_code(self) -> None:
        state = _make_state()
        route = _make_route("build", projects=["p1"])
        with mock.patch("builtins.print") as mock_print:
            print_interactive_failure_details(
                route=route,
                state=state,
                code=42,
                runtime=mock.MagicMock(),
                test_failure_details_available_fn=lambda r, s: False,
                print_test_failure_details_fn=lambda r, s, **kw: False,
                print_project_action_failure_details_fn=lambda r, s, **kw: False,
            )
        mock_print.assert_called_once_with("Command failed (exit 42).")


if __name__ == "__main__":
    unittest.main()
