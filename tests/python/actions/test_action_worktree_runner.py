from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.actions import action_worktree_runner  # noqa: E402
from envctl_engine.actions.action_worktree_runner import (  # noqa: E402
    ActionWorktreeDeleteRunner,
    CurrentWorktreeTargetResolver,
    repo_root_from_worktree_layout,
    resolve_current_worktree_target,
    run_delete_worktree_action,
)
from envctl_engine.actions.action_command_orchestrator import ActionCommandOrchestrator  # noqa: E402
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
    def test_worktree_runner_uses_named_owners_for_target_resolution_and_delete_execution(self) -> None:
        source = Path(action_worktree_runner.__file__).read_text(encoding="utf-8")
        target_resolution_source = (
            REPO_ROOT / "python/envctl_engine/actions/action_worktree_target_resolution.py"
        ).read_text(encoding="utf-8")
        self_destruct_source = (
            REPO_ROOT / "python/envctl_engine/actions/action_worktree_self_destruct.py"
        ).read_text(encoding="utf-8")

        self.assertIn("class ActionWorktreeDeleteRunner", source)
        self.assertIn("return ActionWorktreeDeleteRunner(", source)
        self.assertIn("class CurrentWorktreeTargetResolver", target_resolution_source)
        self.assertIn("def main_repo_root_for_worktree", target_resolution_source)
        self.assertIn("def run_self_destruct_worktree_action", self_destruct_source)
        self.assertIn("def spawn_self_destruct_helper", self_destruct_source)
        self.assertTrue(callable(ActionWorktreeDeleteRunner.execute))
        self.assertTrue(callable(CurrentWorktreeTargetResolver.resolve))

    def test_repo_root_from_worktree_layout_detects_nested_and_flat_tree_layouts(self) -> None:
        repo = Path("/tmp/repo").resolve()

        self.assertEqual(repo_root_from_worktree_layout(repo / "trees" / "feature-a" / "1", "trees"), repo)
        self.assertEqual(repo_root_from_worktree_layout(repo / "trees-feature-a-1", "trees"), repo)
        self.assertIsNone(repo_root_from_worktree_layout(Path("/tmp/other"), ""))

    def test_resolve_current_worktree_target_discovers_matching_current_tree(self) -> None:
        repo = Path("/tmp/repo").resolve()
        tree_root = repo / "trees" / "feature-a" / "1"
        runtime = SimpleNamespace(
            env={"ENVCTL_INVOCATION_CWD": str(tree_root)},
            raw_runtime=SimpleNamespace(config=SimpleNamespace(base_dir=repo, trees_dir_name="trees")),
        )

        target = resolve_current_worktree_target(
            runtime=runtime,
            require_configured_main_root=True,
            current_cwd=lambda: Path("/should/not/be/used"),
            discover_tree_projects_fn=lambda repo_root, trees_dir_name: [("feature-a-1", tree_root)]
            if repo_root == repo and trees_dir_name == "trees"
            else [],
            main_repo_root_for_linked_worktree_fn=lambda _worktree_root: None,
            git_main_repo_root_for_worktree_fn=lambda _worktree_root, trees_dir_name=None: repo,
        )

        self.assertIsNotNone(target)
        self.assertEqual(getattr(target, "name"), "feature-a-1")
        self.assertEqual(getattr(target, "root"), tree_root)

    def test_resolve_current_worktree_target_accepts_external_linked_checkout_in_both_modes(self) -> None:
        repo = Path("/tmp/repo").resolve()
        linked_root = Path("/tmp/envctl-deep-code-cleanup").resolve()
        invocation_cwd = linked_root / "python" / "envctl_engine"

        def run(command, *, cwd, timeout):  # noqa: ANN001
            self.assertEqual(timeout, 10.0)
            if command == ["git", "rev-parse", "--show-toplevel"]:
                return SimpleNamespace(returncode=0, stdout=f"{linked_root}\n")
            if command == ["git", "branch", "--show-current"]:
                self.assertEqual(Path(cwd), linked_root)
                return SimpleNamespace(returncode=0, stdout="agent/deep-code-cleanup\n")
            return SimpleNamespace(returncode=1, stdout="")

        runtime = SimpleNamespace(
            env={"ENVCTL_INVOCATION_CWD": str(invocation_cwd)},
            raw_runtime=SimpleNamespace(
                config=SimpleNamespace(base_dir=repo, trees_dir_name="trees"),
                process_runner=SimpleNamespace(run=run),
            ),
        )

        for require_configured_main_root in (False, True):
            with self.subTest(require_configured_main_root=require_configured_main_root):
                target = resolve_current_worktree_target(
                    runtime=runtime,
                    require_configured_main_root=require_configured_main_root,
                    require_configured_root_match=True,
                    current_cwd=lambda: Path("/should/not/be/used"),
                    discover_tree_projects_fn=lambda _repo_root, _trees_dir_name: [],
                    main_repo_root_for_linked_worktree_fn=lambda _worktree_root: None,
                    git_main_repo_root_for_worktree_fn=lambda **_kwargs: repo,
                )

                self.assertIsNotNone(target)
                self.assertEqual(getattr(target, "name"), "agent/deep-code-cleanup")
                self.assertEqual(getattr(target, "root"), linked_root)

    def test_resolve_current_worktree_target_does_not_synthesize_main_checkout(self) -> None:
        repo = Path("/tmp/repo").resolve()
        runtime = SimpleNamespace(
            env={"ENVCTL_INVOCATION_CWD": str(repo / "python")},
            raw_runtime=SimpleNamespace(
                config=SimpleNamespace(base_dir=repo, trees_dir_name="trees"),
                process_runner=SimpleNamespace(
                    run=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=f"{repo}\n")
                ),
            ),
        )

        target = resolve_current_worktree_target(
            runtime=runtime,
            require_configured_main_root=True,
            require_configured_root_match=True,
            discover_tree_projects_fn=lambda _repo_root, _trees_dir_name: [],
            git_main_repo_root_for_worktree_fn=lambda **_kwargs: repo,
        )

        self.assertIsNone(target)

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

    def test_self_destruct_worktree_spawns_detached_delete_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            tree_root = repo_root / "trees" / "feature-a" / "1"
            (repo_root / ".git").mkdir(parents=True, exist_ok=True)
            tree_root.mkdir(parents=True, exist_ok=True)

            process_runner = SimpleNamespace(
                run=lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=f"{repo_root}\n", stderr=""),
                start_background=lambda cmd, **kwargs: SimpleNamespace(pid=4321, cmd=cmd, kwargs=kwargs),
            )
            runtime = SimpleNamespace(
                env={},
                config=SimpleNamespace(base_dir=repo_root),
                raw={},
                process_runner=process_runner,
                _emit=lambda *_args, **_kwargs: None,
                _trees_root_for_worktree=lambda _path: repo_root / "trees",
                _discover_projects=lambda *, mode: [SimpleNamespace(name="feature-a-1", root=tree_root)],
                _selectors_from_passthrough=lambda _args: set(),
                _try_load_existing_state=lambda *args, **kwargs: None,
                _project_name_from_service=lambda _name: "",
                _select_project_targets=lambda **_kwargs: None,
                _blast_worktree_before_delete=lambda **_kwargs: [],
            )
            orchestrator = ActionCommandOrchestrator(runtime)

            with patch("envctl_engine.actions.action_command_orchestrator.Path.cwd", return_value=tree_root):
                code = orchestrator.run_self_destruct_worktree_action(parse_route(["self-destruct-worktree"], env={}))

            self.assertEqual(code, 0)

    def test_run_self_destruct_worktree_action_uses_explicit_current_worktree_safety_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tree_root = Path(tmpdir).resolve()
            target = SimpleNamespace(name="feature-a-1", root=tree_root)
            warnings: list[str] = []
            calls: list[tuple[str, object]] = []

            runtime = SimpleNamespace(
                _blast_worktree_before_delete=lambda **kwargs: (
                    calls.append(("cleanup", kwargs)) or ["cleanup warning"]
                ),
                _trees_root_for_worktree=lambda value: calls.append(("trees_root", value)) or tree_root.parent,
            )
            orchestrator = SimpleNamespace(
                runtime=runtime,
                resolve_targets=lambda route, *, trees_only: calls.append(("resolve", (route.command, trees_only)))
                or ([target], None),
                _main_repo_root_for_worktree=lambda value: calls.append(("main_repo", value)) or tree_root.parent,
                _spawn_self_destruct_helper=lambda **kwargs: calls.append(("spawn", kwargs)) or True,
            )

            with (
                patch("envctl_engine.actions.action_worktree_runner.Path.cwd", return_value=tree_root),
                patch("builtins.print", side_effect=lambda value: warnings.append(str(value))),
            ):
                code = action_worktree_runner.run_self_destruct_worktree_action(
                    orchestrator,
                    parse_route(["self-destruct-worktree"], env={}),
                )

            self.assertEqual(code, 0)
            self.assertIn("Warning: cleanup warning", warnings)
            self.assertIn(
                "Self-destruct launched for feature-a-1. This worktree will be removed after envctl exits.",
                warnings,
            )
            self.assertEqual(calls[0], ("resolve", ("self-destruct-worktree", True)))
            self.assertTrue(any(kind == "cleanup" for kind, _payload in calls))
            self.assertTrue(any(kind == "spawn" for kind, _payload in calls))


if __name__ == "__main__":
    unittest.main()
