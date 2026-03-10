from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import sys

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from envctl_engine.actions.action_worktree_runner import run_delete_worktree_action  # noqa: E402
from envctl_engine.runtime.command_router import parse_route  # noqa: E402


class _OrchestratorStub:
    def __init__(self, runtime: object, targets: list[object]) -> None:
        self.runtime = runtime
        self._targets = targets
        self.statuses: list[str] = []

    def resolve_targets(self, route, *, trees_only: bool):  # noqa: ANN001
        _ = route
        return (self._targets if trees_only else [], None)

    def _emit_status(self, message: str) -> None:
        self.statuses.append(message)

    @staticmethod
    def _command_start_status(command_name: str, targets: list[object]) -> str:
        return f"Running {command_name} for {len(targets)} targets..."


class _SpinnerStub:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def start(self) -> None:
        self.events.append(("start", ""))

    def update(self, message: str) -> None:
        self.events.append(("update", message))

    def succeed(self, message: str) -> None:
        self.events.append(("success", message))

    def fail(self, message: str) -> None:
        self.events.append(("fail", message))


class _SpinnerContext:
    def __init__(self, active: _SpinnerStub) -> None:
        self.active = active

    def __enter__(self) -> _SpinnerStub:
        return self.active

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001
        _ = exc_type, exc, tb
        return False


class ActionWorktreeRunnerTests(unittest.TestCase):
    def test_run_delete_worktree_action_runs_cleanup_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            tree_root = repo_root / "trees" / "feature-a" / "1"
            tree_root.mkdir(parents=True, exist_ok=True)
            target = SimpleNamespace(name="feature-a-1", root=str(tree_root))
            events: list[tuple[str, dict[str, object]]] = []
            cleanup_calls: list[tuple[str, Path, str]] = []
            spinner = _SpinnerStub()

            runtime = SimpleNamespace(
                env={},
                config=SimpleNamespace(base_dir=repo_root),
                process_runner=object(),
                _emit=lambda event, **payload: events.append((event, payload)),
                _trees_root_for_worktree=lambda _path: repo_root / "trees",
                _blast_worktree_before_delete=lambda **kwargs: (
                    cleanup_calls.append(
                        (str(kwargs["project_name"]), Path(kwargs["project_root"]), str(kwargs["source_command"]))
                    )
                    or ["cleanup warning"]
                ),
            )
            orchestrator = _OrchestratorStub(runtime, [target])

            with (
                patch(
                    "envctl_engine.actions.action_worktree_runner.resolve_spinner_policy",
                    return_value=SimpleNamespace(enabled=True),
                ),
                patch("envctl_engine.actions.action_worktree_runner.emit_spinner_policy"),
                patch("envctl_engine.actions.action_worktree_runner.use_spinner_policy"),
                patch("envctl_engine.actions.action_worktree_runner.spinner", return_value=_SpinnerContext(spinner)),
                patch(
                    "envctl_engine.actions.action_worktree_runner.delete_worktree_path",
                    return_value=SimpleNamespace(success=True, message="deleted"),
                ) as delete_mock,
            ):
                route = parse_route(["delete-worktree", "--project", "feature-a-1"], env={})
                code = run_delete_worktree_action(orchestrator, route)

            self.assertEqual(code, 0)
            self.assertEqual(cleanup_calls, [("feature-a-1", tree_root, "delete-worktree")])
            delete_mock.assert_called_once()
            self.assertIn("cleanup warning", orchestrator.statuses)
            self.assertTrue(any(event[0] == "success" for event in spinner.events))
            self.assertTrue(any(name == "action.command.start" for name, _ in events))

    def test_run_delete_worktree_action_skips_cleanup_in_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            tree_root = repo_root / "trees" / "feature-a" / "1"
            tree_root.mkdir(parents=True, exist_ok=True)
            target = SimpleNamespace(name="feature-a-1", root=str(tree_root))
            cleanup_calls: list[str] = []

            runtime = SimpleNamespace(
                env={},
                config=SimpleNamespace(base_dir=repo_root),
                process_runner=object(),
                _emit=lambda *_args, **_kwargs: None,
                _trees_root_for_worktree=lambda _path: repo_root / "trees",
                _blast_worktree_before_delete=lambda **_kwargs: cleanup_calls.append("called") or [],
            )
            orchestrator = _OrchestratorStub(runtime, [target])

            with (
                patch(
                    "envctl_engine.actions.action_worktree_runner.resolve_spinner_policy",
                    return_value=SimpleNamespace(enabled=False),
                ),
                patch("envctl_engine.actions.action_worktree_runner.emit_spinner_policy"),
                patch("envctl_engine.actions.action_worktree_runner.use_spinner_policy"),
                patch(
                    "envctl_engine.actions.action_worktree_runner.spinner", return_value=_SpinnerContext(_SpinnerStub())
                ),
                patch(
                    "envctl_engine.actions.action_worktree_runner.delete_worktree_path",
                    return_value=SimpleNamespace(success=True, message="dry-run delete"),
                ) as delete_mock,
            ):
                route = parse_route(["delete-worktree", "--project", "feature-a-1", "--dry-run"], env={})
                code = run_delete_worktree_action(orchestrator, route)

            self.assertEqual(code, 0)
            self.assertEqual(cleanup_calls, [])
            delete_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
