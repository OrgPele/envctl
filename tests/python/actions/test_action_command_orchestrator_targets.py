from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch
import tempfile

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.actions.action_command_orchestrator import ActionCommandOrchestrator
from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState
from envctl_engine.ui.target_selector import TargetSelection


class _RuntimeStub:
    def __init__(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self.env: dict[str, str] = {}
        self.config = SimpleNamespace(base_dir=Path("/tmp"), raw={})
        self.process_runner = SimpleNamespace()
        self._dashboard_pr_url_cache: dict[str, object] = {}
        self._emitted: list[tuple[str, dict[str, object]]] = []
        runtime_root = Path(self._tmpdir.name) / "runtime"
        self.state_repository = SimpleNamespace(
            run_dir_path=lambda run_id: runtime_root / "runs" / str(run_id),
            save_resume_state=self._save_resume_state,
        )
        self._latest_state: RunState | None = None

    def _discover_projects(self, *, mode: str):  # noqa: ANN001
        return [SimpleNamespace(name="alpha"), SimpleNamespace(name="beta")]

    @staticmethod
    def _selectors_from_passthrough(_args):  # noqa: ANN001
        return set()

    def _try_load_existing_state(self, *args, **kwargs):  # noqa: ANN001, ARG002
        return self._latest_state

    def _project_name_from_service(self, _name: str) -> str:
        return ""

    def _select_project_targets(self, **_kwargs):  # noqa: ANN001
        return TargetSelection(cancelled=True)

    def _emit(self, event: str, **payload: object) -> None:
        self._emitted.append((event, dict(payload)))

    def _save_resume_state(self, *, state, emit, runtime_map_builder):  # noqa: ANN001, ARG002
        self._latest_state = state
        return {}


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
        runtime._latest_state = RunState(run_id="run-1", mode="main")

        handler = orchestrator._project_action_success_handler("pr", "main", True)  # noqa: SLF001
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

    def test_project_action_failure_handler_persists_summary_and_report_path(self) -> None:
        runtime = _RuntimeStub()
        runtime._latest_state = RunState(run_id="run-1", mode="main")
        orchestrator = ActionCommandOrchestrator(runtime)

        handler = orchestrator._project_action_failure_handler("migrate", "main")  # noqa: SLF001
        handler(
            SimpleNamespace(name="Main", root=Path("/tmp"), index=1, total=1, target_obj=SimpleNamespace(name="Main")),
            "alembic failed\nline 2\nline 3",
        )

        assert runtime._latest_state is not None
        metadata = runtime._latest_state.metadata.get("project_action_reports")
        self.assertIsInstance(metadata, dict)
        assert isinstance(metadata, dict)
        project_entry = metadata.get("Main")
        self.assertIsInstance(project_entry, dict)
        assert isinstance(project_entry, dict)
        migrate_entry = project_entry.get("migrate")
        self.assertIsInstance(migrate_entry, dict)
        assert isinstance(migrate_entry, dict)
        self.assertEqual(migrate_entry.get("status"), "failed")
        self.assertIn("alembic failed", str(migrate_entry.get("summary", "")))
        report_path = Path(str(migrate_entry.get("report_path", "")))
        self.assertTrue(report_path.is_file())
        self.assertIn("alembic failed", report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
