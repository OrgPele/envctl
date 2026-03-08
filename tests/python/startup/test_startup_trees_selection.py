from __future__ import annotations

import unittest
from types import SimpleNamespace

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.runtime.command_router import Route
from envctl_engine.state.models import RunState, ServiceRecord
from envctl_engine.startup.startup_orchestrator import StartupOrchestrator
from envctl_engine.ui.selection_types import TargetSelection


class _RuntimeStub:
    def __init__(self, *, can_tty: bool = True) -> None:
        self._can_tty = can_tty
        self.events: list[tuple[str, dict[str, object]]] = []
        self.selection = TargetSelection(cancelled=False)
        self.selection_kwargs: dict[str, object] | None = None
        self.state: RunState | None = None

    def _emit(self, event: str, **payload: object) -> None:
        self.events.append((event, dict(payload)))

    def _can_interactive_tty(self) -> bool:
        return self._can_tty

    def _try_load_existing_state(self, *, mode: str, strict_mode_match: bool = False):  # noqa: ANN001, ARG002
        return self.state

    def _select_project_targets(self, **kwargs):  # noqa: ANN001
        self.selection_kwargs = dict(kwargs)
        return self.selection

    @staticmethod
    def _project_name_from_service(name: str) -> str:
        raw = str(name).strip()
        for suffix in (" Backend", " Frontend"):
            if raw.endswith(suffix):
                return raw[: -len(suffix)].strip()
        return ""


class StartupTreesSelectionTests(unittest.TestCase):
    @staticmethod
    def _trees_route(*, raw_args: list[str] | None = None) -> Route:
        args = ["--trees"] if raw_args is None else list(raw_args)
        return Route(
            command="start",
            mode="trees",
            raw_args=args,
            passthrough_args=[],
            projects=[],
            flags={},
        )

    def test_trees_start_selection_required_for_default_or_explicit_trees_start(self) -> None:
        runtime = _RuntimeStub()
        orchestrator = StartupOrchestrator(runtime)

        self.assertTrue(
            orchestrator._trees_start_selection_required(route=self._trees_route(raw_args=["--trees"]), runtime_mode="trees")
        )
        self.assertTrue(
            orchestrator._trees_start_selection_required(route=self._trees_route(raw_args=[]), runtime_mode="trees")
        )
        self.assertFalse(
            orchestrator._trees_start_selection_required(
                route=Route(command="plan", mode="trees", raw_args=["--plan"], passthrough_args=[], projects=[], flags={}),
                runtime_mode="trees",
            )
        )
        self.assertFalse(
            orchestrator._trees_start_selection_required(
                route=Route(
                    command="start",
                    mode="trees",
                    raw_args=[],
                    passthrough_args=[],
                    projects=["alpha"],
                    flags={},
                ),
                runtime_mode="trees",
            )
        )

    def test_select_start_tree_projects_preselects_from_previous_trees_state(self) -> None:
        runtime = _RuntimeStub(can_tty=True)
        runtime.state = RunState(
            run_id="run-prev",
            mode="trees",
            services={
                "alpha Backend": ServiceRecord(name="alpha Backend", type="backend", cwd="."),
                "gamma Frontend": ServiceRecord(name="gamma Frontend", type="frontend", cwd="."),
            },
        )
        runtime.selection = TargetSelection(project_names=["alpha", "gamma"])
        orchestrator = StartupOrchestrator(runtime)

        contexts = [SimpleNamespace(name="alpha"), SimpleNamespace(name="beta"), SimpleNamespace(name="gamma")]
        selected = orchestrator._select_start_tree_projects(route=self._trees_route(), project_contexts=contexts)

        self.assertEqual([ctx.name for ctx in selected], ["alpha", "gamma"])
        self.assertIsNotNone(runtime.selection_kwargs)
        assert runtime.selection_kwargs is not None
        self.assertEqual(runtime.selection_kwargs.get("prompt"), "Run worktrees for")
        self.assertEqual(runtime.selection_kwargs.get("initial_project_names"), ["alpha", "gamma"])

    def test_select_start_tree_projects_requires_explicit_selection_without_tty(self) -> None:
        runtime = _RuntimeStub(can_tty=False)
        runtime.selection = TargetSelection(project_names=["alpha"])
        orchestrator = StartupOrchestrator(runtime)
        contexts = [SimpleNamespace(name="alpha"), SimpleNamespace(name="beta")]

        selected = orchestrator._select_start_tree_projects(route=self._trees_route(), project_contexts=contexts)

        self.assertEqual(selected, [])
        self.assertIsNone(runtime.selection_kwargs)
        self.assertTrue(any(name == "trees.start.selector.skipped" for name, _ in runtime.events))


if __name__ == "__main__":
    unittest.main()
