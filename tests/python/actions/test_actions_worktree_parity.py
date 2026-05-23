from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from tests.python.actions.actions_parity_test_support import (
    PythonEngineRuntime,
    _ActionsParityTestCase,
    _FakeRunner,
    parse_route,
)


class ActionsWorktreeParityTests(_ActionsParityTestCase):
    def test_delete_worktree_supports_project_selection_and_all(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            tree_b = repo / "trees" / "feature-b" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)
            tree_b.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            delete_one = parse_route(
                ["delete-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code_one = engine.dispatch(delete_one)
            self.assertEqual(code_one, 0)
            self.assertFalse(tree_a.exists())
            self.assertTrue(tree_b.exists())

            delete_all_without_yes = parse_route(
                ["delete-worktree", "--all"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code_guard = engine.dispatch(delete_all_without_yes)
            self.assertEqual(code_guard, 1)
            self.assertTrue(tree_b.exists())

            delete_all_with_yes = parse_route(
                ["delete-worktree", "--all", "--yes"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code_all = engine.dispatch(delete_all_with_yes)
            self.assertEqual(code_all, 0)
            self.assertFalse(tree_b.exists())

    def test_delete_worktree_supports_flat_trees_feature_roots(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees-feature-a" / "1"
            tree_b = repo / "trees-feature-b" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)
            tree_b.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            delete_one = parse_route(
                ["delete-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code_one = engine.dispatch(delete_one)

            self.assertEqual(code_one, 0)
            self.assertFalse(tree_a.exists())
            self.assertTrue(tree_b.exists())

    def test_delete_worktree_runs_blast_cleanup_before_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            cleanup_calls: list[tuple[str, Path, str]] = []

            def fake_blast_worktree_before_delete(*, project_name: str, project_root: Path, source_command: str):
                cleanup_calls.append((project_name, project_root, source_command))
                return []

            engine._blast_worktree_before_delete = fake_blast_worktree_before_delete  # type: ignore[assignment]
            route = parse_route(
                ["delete-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(cleanup_calls, [("feature-a-1", tree_a.resolve(), "delete-worktree")])
            self.assertFalse(tree_a.exists())

    def test_delete_worktree_removes_recorded_cgc_context_before_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (tree_a / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (tree_a / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
            (tree_a / ".envctl-state" / "code-intelligence.json").write_text(
                json.dumps({"cgc_context": "Repo-feature-a-1"}) + "\n",
                encoding="utf-8",
            )

            class _DeleteRunner(_FakeRunner):
                def run(self, cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                    self.run_calls.append((tuple(str(token) for token in cmd), str(cwd)))
                    self.run_envs.append(dict(env) if isinstance(env, dict) else None)
                    command = [str(token) for token in cmd]
                    if command[:2] == ["sh", "-c"]:
                        return SimpleNamespace(returncode=0, stdout="deleted\n", stderr="")
                    return SimpleNamespace(returncode=1, stdout="", stderr="git failed")

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _DeleteRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]
            engine._blast_worktree_before_delete = lambda **_kwargs: []  # type: ignore[assignment]
            route = parse_route(
                ["delete-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertFalse(tree_a.exists())
            self.assertGreaterEqual(len(fake_runner.run_calls), 2)
            self.assertEqual(fake_runner.run_calls[0][0][:2], ("sh", "-c"))
            self.assertEqual(
                fake_runner.run_envs[0].get("ENVCTL_CGC_CONTEXT_TO_DELETE") if fake_runner.run_envs[0] else None,
                "Repo-feature-a-1",
            )
            self.assertIn("cgc context delete", fake_runner.run_calls[0][0][2])
            self.assertEqual(fake_runner.run_calls[1][0][:5], ("git", "-C", str(repo.resolve()), "worktree", "remove"))

    def test_delete_worktree_does_not_remove_unmanaged_inherited_cgc_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (tree_a / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (tree_a / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
            (tree_a / ".envctl-state" / "code-intelligence.json").write_text(
                json.dumps(
                    {
                        "cgc_context": "Repo-feature-a-1",
                        "cgc_active_context": "Repo",
                        "cgc_context_managed": False,
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]
            engine._blast_worktree_before_delete = lambda **_kwargs: []  # type: ignore[assignment]
            route = parse_route(
                ["delete-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertFalse(tree_a.exists())
            self.assertEqual(fake_runner.run_calls[0][0][:5], ("git", "-C", str(repo.resolve()), "worktree", "remove"))

    def test_blast_worktree_alias_routes_to_delete_flow_with_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            cleanup_calls: list[tuple[str, Path, str]] = []

            def fake_blast_worktree_before_delete(*, project_name: str, project_root: Path, source_command: str):
                cleanup_calls.append((project_name, project_root, source_command))
                return []

            engine._blast_worktree_before_delete = fake_blast_worktree_before_delete  # type: ignore[assignment]
            route = parse_route(
                ["blast-worktree", "--project", "feature-a-1"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(cleanup_calls, [("feature-a-1", tree_a.resolve(), "blast-worktree")])
            self.assertFalse(tree_a.exists())

    def test_delete_worktree_dry_run_skips_blast_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            runtime = Path(tmpdir) / "runtime"
            tree_a = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            tree_a.mkdir(parents=True, exist_ok=True)

            engine = PythonEngineRuntime(self._config(repo, runtime), env={})
            fake_runner = _FakeRunner(returncode=1)
            engine.process_runner = fake_runner  # type: ignore[assignment]

            cleanup_calls: list[tuple[str, Path, str]] = []

            def fake_blast_worktree_before_delete(*, project_name: str, project_root: Path, source_command: str):
                cleanup_calls.append((project_name, project_root, source_command))
                return []

            engine._blast_worktree_before_delete = fake_blast_worktree_before_delete  # type: ignore[assignment]
            route = parse_route(
                ["delete-worktree", "--project", "feature-a-1", "--dry-run"],
                env={"ENVCTL_DEFAULT_MODE": "trees"},
            )
            code = engine.dispatch(route)

            self.assertEqual(code, 0)
            self.assertEqual(cleanup_calls, [])
            self.assertTrue(tree_a.exists())
            self.assertEqual(fake_runner.run_calls, [])

