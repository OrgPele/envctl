from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.actions.action_command_orchestrator import ActionCommandOrchestrator
from envctl_engine.runtime.command_router import Route
from envctl_engine.ui.target_selector import TargetSelection


class _RuntimeStub:
    def __init__(self) -> None:
        self.env: dict[str, str] = {}
        self.config = SimpleNamespace(base_dir=Path("/tmp"), raw={})
        self.process_runner = SimpleNamespace()
        self._dashboard_pr_url_cache: dict[str, object] = {}
        self._emitted: list[tuple[str, dict[str, object]]] = []

    def _discover_projects(self, *, mode: str):  # noqa: ANN001
        return [SimpleNamespace(name="alpha"), SimpleNamespace(name="beta")]

    @staticmethod
    def _selectors_from_passthrough(_args):  # noqa: ANN001
        return set()

    def _try_load_existing_state(self, *args, **kwargs):  # noqa: ANN001, ARG002
        return None

    def _project_name_from_service(self, _name: str) -> str:
        return ""

    def _select_project_targets(self, **_kwargs):  # noqa: ANN001
        return TargetSelection(cancelled=True)

    def _emit(self, event: str, **payload: object) -> None:
        self._emitted.append((event, dict(payload)))


class ActionCommandTargetTests(unittest.TestCase):
    def test_runtime_facade_routes_target_dependencies(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)

        projects = orchestrator.runtime.discover_projects(mode="trees")

        self.assertEqual([project.name for project in projects], ["alpha", "beta"])
        self.assertEqual(orchestrator.runtime.selectors_from_passthrough(["ignored"]), set())

    def test_resolve_targets_uses_interactive_selection(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="test", mode="trees", flags={"interactive_command": True})

        selection = TargetSelection(all_selected=True)
        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch.object(runtime, "_select_project_targets", return_value=selection),
        ):
            targets, error = orchestrator.resolve_targets(route, trees_only=False)

        self.assertIsNone(error)
        self.assertEqual(len(targets), 2)

    def test_resolve_targets_does_not_flush_pending_input_for_interactive_command(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="test", mode="trees", flags={"interactive_command": True})

        selection = TargetSelection(all_selected=True)
        with (
            patch(
                "envctl_engine.actions.action_command_orchestrator.RuntimeTerminalUI.flush_pending_interactive_input"
            ) as flush_pending,
            patch.object(runtime, "_select_project_targets", return_value=selection),
        ):
            targets, error = orchestrator.resolve_targets(route, trees_only=False)

        self.assertIsNone(error)
        self.assertEqual(len(targets), 2)
        flush_pending.assert_not_called()

    def test_resolve_targets_does_not_flush_for_non_interactive_command(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        route = Route(command="test", mode="trees")

        selection = TargetSelection(all_selected=True)
        with (
            patch("envctl_engine.ui.dashboard.terminal_ui.RuntimeTerminalUI._can_interactive_tty", return_value=True),
            patch(
                "envctl_engine.actions.action_command_orchestrator.RuntimeTerminalUI.flush_pending_interactive_input"
            ) as flush_pending,
            patch.object(runtime, "_select_project_targets", return_value=selection),
        ):
            targets, error = orchestrator.resolve_targets(route, trees_only=False)

        self.assertIsNone(error)
        self.assertEqual(len(targets), 2)
        flush_pending.assert_not_called()

    def test_pr_success_handler_clears_dashboard_cache_and_emits_created_url_status(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = ActionCommandOrchestrator(runtime)
        runtime._dashboard_pr_url_cache = {"stale": ("expires", None)}

        handler = orchestrator._project_action_success_handler("pr", True)  # noqa: SLF001
        self.assertIsNotNone(handler)

        handler(  # type: ignore[misc]
            SimpleNamespace(name="Main", root=Path("/tmp"), index=1, total=1, target_obj=SimpleNamespace(name="Main")),
            SimpleNamespace(stdout="https://github.com/kfiramar/envctl/pull/21\n", stderr="", returncode=0),
        )

        self.assertEqual(runtime._dashboard_pr_url_cache, {})
        self.assertIn(
            ("ui.status", {"message": "PR created: https://github.com/kfiramar/envctl/pull/21"}),
            runtime._emitted,
        )


if __name__ == "__main__":
    unittest.main()
