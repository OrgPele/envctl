from __future__ import annotations

import tempfile
import unittest
from contextlib import contextmanager
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.config import load_config
from envctl_engine.runtime.engine_runtime import PythonEngineRuntime
from envctl_engine.ui.spinner_service import SpinnerPolicy


class PlanningWorktreeSetupTests(unittest.TestCase):
    def _runtime(self, repo: Path, runtime: Path, *, env: dict[str, str] | None = None) -> PythonEngineRuntime:
        resolved_env = dict(env or {})
        config = load_config(
            {
                "RUN_REPO_ROOT": str(repo),
                "RUN_SH_RUNTIME_DIR": str(runtime),
                **resolved_env,
            }
        )
        return PythonEngineRuntime(config, env=resolved_env)

    def test_invalid_planning_selection_is_strict_and_no_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "trees" / "feature-a" / "1").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime)
            contexts = engine._discover_projects(mode="trees")
            route = parse_route(["--plan", "implementations/missing"], env={})

            out = StringIO()
            with redirect_stdout(out):
                selected = engine._select_plan_projects(route, contexts)

            self.assertEqual(selected, [])
            self.assertIn("Planning file not found", out.getvalue())

    def test_plan_selection_creates_missing_worktrees_for_requested_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})
            initial = engine._discover_projects(mode="trees")
            self.assertEqual(initial, [])
            route = parse_route(["--plan", "implementations/task,implementations/task"], env={})

            selected = engine._select_plan_projects(route, initial)

            names = [ctx.name for ctx in selected]
            self.assertEqual(names, ["implementations_task-1", "implementations_task-2"])
            self.assertTrue((repo / "trees" / "implementations_task" / "1").is_dir())
            self.assertTrue((repo / "trees" / "implementations_task" / "2").is_dir())

    def test_plan_selection_create_missing_worktrees_fails_without_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime)
            initial = engine._discover_projects(mode="trees")
            route = parse_route(["--plan", "implementations/task,implementations/task"], env={})

            out = StringIO()
            with redirect_stdout(out):
                selected = engine._select_plan_projects(route, initial)

            self.assertEqual(selected, [])
            self.assertIn("failed creating worktree implementations_task/1", out.getvalue().lower())

    def test_plan_selection_deletes_excess_worktrees_to_match_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")
            for iteration in (1, 2, 3):
                (repo / "trees" / "implementations_task" / str(iteration)).mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime)
            cleanup_calls: list[tuple[str, Path, str]] = []

            def fake_blast_worktree_before_delete(*, project_name: str, project_root: Path, source_command: str):
                cleanup_calls.append((project_name, project_root, source_command))
                return []

            engine._blast_worktree_before_delete = fake_blast_worktree_before_delete  # type: ignore[assignment]
            contexts = engine._discover_projects(mode="trees")
            route = parse_route(["--plan", "implementations/task"], env={})

            selected = engine._select_plan_projects(route, contexts)

            self.assertEqual([ctx.name for ctx in selected], ["implementations_task-1"])
            self.assertTrue((repo / "trees" / "implementations_task" / "1").is_dir())
            self.assertFalse((repo / "trees" / "implementations_task" / "2").exists())
            self.assertFalse((repo / "trees" / "implementations_task" / "3").exists())
            self.assertEqual(
                cleanup_calls,
                [
                    (
                        "implementations_task-3",
                        (repo / "trees" / "implementations_task" / "3").resolve(),
                        "blast-worktree",
                    ),
                    (
                        "implementations_task-2",
                        (repo / "trees" / "implementations_task" / "2").resolve(),
                        "blast-worktree",
                    ),
                ],
            )

    def test_plan_zero_target_moves_plan_to_done_when_keep_plan_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            plan_file = repo / "todo" / "plans" / "implementations" / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime)
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001
            synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 0},
                raw_projects=raw_projects,
                keep_plan=False,
            )
            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertFalse(plan_file.exists())
            done_file = repo / "todo" / "done" / "implementations" / "task.md"
            self.assertTrue(done_file.is_file())

    def test_plan_zero_target_reports_blast_and_delete_before_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            plan_file = repo / "todo" / "plans" / "implementations" / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime)
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001
            out = StringIO()
            with redirect_stdout(out):
                synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                    plan_counts={"implementations/task.md": 0},
                    raw_projects=raw_projects,
                    keep_plan=False,
                )

            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertIn("Blasted and deleted 1 worktree(s) for implementations/task.md.", out.getvalue())

    def test_plan_zero_target_does_not_move_inactive_plan_to_done(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            plan_file = repo / "todo" / "plans" / "implementations" / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime)
            synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 0},
                raw_projects=[],
                keep_plan=False,
            )

            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertTrue(plan_file.exists())
            self.assertFalse((repo / "todo" / "done" / "implementations" / "task.md").exists())

    def test_plan_zero_target_keeps_plan_when_keep_plan_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            plan_file = repo / "todo" / "plans" / "implementations" / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime)
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001
            synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 0},
                raw_projects=raw_projects,
                keep_plan=True,
            )
            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertTrue(plan_file.exists())
            done_file = repo / "todo" / "done" / "implementations" / "task.md"
            self.assertFalse(done_file.exists())

    def test_plan_zero_target_moves_plan_to_sibling_done_root_for_custom_planning_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            plan_dir = repo / "work" / "plans" / "implementations"
            plan_dir.mkdir(parents=True, exist_ok=True)
            plan_file = plan_dir / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_PLANNING_DIR": "work/plans"})
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001
            synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 0},
                raw_projects=raw_projects,
                keep_plan=False,
            )

            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertFalse(plan_file.exists())
            self.assertTrue((repo / "work" / "done" / "implementations" / "task.md").is_file())

    def test_plan_zero_target_done_move_avoids_overwriting_existing_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            plan_dir = repo / "todo" / "plans" / "implementations"
            plan_dir.mkdir(parents=True, exist_ok=True)
            plan_file = plan_dir / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")
            done_dir = repo / "todo" / "done" / "implementations"
            done_dir.mkdir(parents=True, exist_ok=True)
            (done_dir / "task.md").write_text("# previous\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime)
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001
            synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 0},
                raw_projects=raw_projects,
                keep_plan=False,
            )

            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertTrue((done_dir / "task.md").is_file())
            moved = sorted(done_dir.glob("task-*.md"))
            self.assertEqual(len(moved), 1)

    def test_setup_worktrees_emits_spinner_policy_and_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})
            events: list[dict[str, object]] = []

            def capture_emit(event: str, **payload: object) -> None:
                entry = {"event": event}
                entry.update(payload)
                events.append(entry)

            engine._emit = capture_emit  # type: ignore[method-assign]
            contexts = engine._discover_projects(mode="main")
            route = parse_route(["--setup-worktrees", "feature-a", "1"], env={})
            spinner_calls: list[tuple[str, bool]] = []

            @contextmanager
            def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
                _ = start_immediately
                spinner_calls.append((message, enabled))

                class _SpinnerStub:
                    def start(self) -> None:
                        return None

                    def update(self, _message: str) -> None:
                        return None

                    def succeed(self, _message: str) -> None:
                        return None

                    def fail(self, _message: str) -> None:
                        return None

                yield _SpinnerStub()

            with (
                patch("envctl_engine.planning.worktree_domain.spinner", side_effect=fake_spinner),
                patch(
                    "envctl_engine.planning.worktree_domain.resolve_spinner_policy",
                    return_value=SpinnerPolicy(
                        mode="auto",
                        enabled=True,
                        reason="",
                        backend="rich",
                        min_ms=0,
                        verbose_events=False,
                    ),
                ),
            ):
                selected = engine._apply_setup_worktree_selection(route, contexts)  # noqa: SLF001

            self.assertTrue(selected)
            self.assertEqual(spinner_calls, [("Setting up worktrees...", True)])
            self.assertTrue(any(item.get("event") == "ui.spinner.policy" for item in events))
            lifecycle = [item for item in events if item.get("event") == "ui.spinner.lifecycle"]
            self.assertTrue(any(item.get("state") == "start" for item in lifecycle))
            self.assertTrue(any(item.get("state") == "success" for item in lifecycle))
            self.assertTrue(any(item.get("state") == "stop" for item in lifecycle))

    def test_sync_plan_worktrees_emits_spinner_policy_and_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})
            events: list[dict[str, object]] = []

            def capture_emit(event: str, **payload: object) -> None:
                entry = {"event": event}
                entry.update(payload)
                events.append(entry)

            engine._emit = capture_emit  # type: ignore[method-assign]
            spinner_calls: list[tuple[str, bool]] = []

            @contextmanager
            def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
                _ = start_immediately
                spinner_calls.append((message, enabled))

                class _SpinnerStub:
                    def start(self) -> None:
                        return None

                    def update(self, _message: str) -> None:
                        return None

                    def succeed(self, _message: str) -> None:
                        return None

                    def fail(self, _message: str) -> None:
                        return None

                yield _SpinnerStub()

            with (
                patch("envctl_engine.planning.worktree_domain.spinner", side_effect=fake_spinner),
                patch(
                    "envctl_engine.planning.worktree_domain.resolve_spinner_policy",
                    return_value=SpinnerPolicy(
                        mode="auto",
                        enabled=True,
                        reason="",
                        backend="rich",
                        min_ms=0,
                        verbose_events=False,
                    ),
                ),
            ):
                synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                    plan_counts={"implementations/task.md": 2},
                    raw_projects=[],
                    keep_plan=True,
                )

            self.assertIsNone(error)
            self.assertEqual(len(synced), 2)
            self.assertEqual(spinner_calls, [("Syncing planning worktrees...", True)])
            self.assertTrue(any(item.get("event") == "ui.spinner.policy" for item in events))
            lifecycle = [item for item in events if item.get("event") == "ui.spinner.lifecycle"]
            self.assertTrue(any(item.get("state") == "start" for item in lifecycle))
            self.assertTrue(any(item.get("state") == "success" for item in lifecycle))
            self.assertTrue(any(item.get("state") == "stop" for item in lifecycle))


if __name__ == "__main__":
    unittest.main()
