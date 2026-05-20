from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
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
from envctl_engine.planning.plan_agent_launch_support import PlanSelectionResult
from envctl_engine.test_output.parser_base import strip_ansi
from envctl_engine.ui.spinner_service import SpinnerPolicy


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


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

    def _read_provenance(self, worktree_root: Path) -> dict[str, object]:
        path = worktree_root / ".envctl-state" / "worktree-provenance.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def _worktree_add_index(self, command: list[str]) -> int:
        try:
            index = command.index("worktree")
        except ValueError as exc:
            raise AssertionError(f"not a worktree command: {command}") from exc
        self.assertLess(index + 1, len(command))
        self.assertEqual(command[index + 1], "add")
        return index

    def _assert_hooks_disabled_for_worktree_add(self, command: list[str]) -> None:
        c_index = command.index("-C")
        self.assertEqual(command[c_index - 2 : c_index], ["-c", "core.hooksPath=/dev/null"])

    def _assert_hooks_inherited_for_worktree_add(self, command: list[str]) -> None:
        self.assertNotIn("core.hooksPath=/dev/null", command)

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

    def test_plan_selection_uses_execution_root_plans_from_linked_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            worktree = repo / "trees" / "feature-a" / "1"
            runtime = root / "runtime"
            gitdir = repo / ".git" / "worktrees" / "feature-a-1"
            gitdir.mkdir(parents=True, exist_ok=True)
            (repo / ".git").mkdir(exist_ok=True)
            (repo / ".envctl").write_text("ENVCTL_DEFAULT_MODE=trees\n", encoding="utf-8")
            (worktree / "todo" / "plans" / "features").mkdir(parents=True, exist_ok=True)
            (worktree / "todo" / "plans" / "features" / "task.md").write_text("# task\n", encoding="utf-8")
            (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")

            engine = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_EXECUTION_ROOT": str(worktree),
                    "ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true",
                },
            )
            route = parse_route(["--plan", "features/task"], env={})

            selected = engine._select_plan_projects(route, [])

            self.assertEqual(engine.config.base_dir, repo.resolve())
            self.assertEqual(engine.config.planning_dir, (worktree / "todo" / "plans").resolve())
            self.assertEqual([ctx.name for ctx in selected], ["features_task-1"])
            self.assertEqual(
                (repo / "trees" / "features_task" / "1" / "MAIN_TASK.md").read_text(encoding="utf-8"),
                "# task\n",
            )


    def test_interactive_plan_dry_run_previews_without_syncing_worktrees_or_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "feature" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime)
            orchestrator = engine.planning_worktree_orchestrator
            route = parse_route(["--plan", "--dry-run"], env={})
            sync_calls: list[dict[str, int]] = []
            save_calls: list[dict[str, int]] = []

            def fake_menu(
                planning_files: list[str],
                selected_counts: dict[str, int],
                existing_counts: dict[str, int],
            ) -> dict[str, int]:
                self.assertEqual(planning_files, ["feature/task.md"])
                self.assertEqual(existing_counts, {"feature/task.md": 0})
                return {"feature/task.md": 1}

            def fake_sync(**kwargs: object) -> object:
                sync_calls.append(dict(kwargs["plan_counts"]))  # type: ignore[index,arg-type]
                return engine._sync_plan_worktrees_from_plan_counts(**kwargs)  # type: ignore[arg-type]

            def fake_save(chosen: dict[str, int]) -> None:
                save_calls.append(dict(chosen))

            with (
                patch.object(orchestrator, "_run_planning_selection_menu", side_effect=fake_menu),
                patch.object(orchestrator, "_sync_plan_worktrees_from_plan_counts", side_effect=fake_sync),
                patch.object(orchestrator, "_save_plan_selection_memory", side_effect=fake_save),
                patch.object(sys.stdin, "isatty", return_value=True),
                patch.object(sys.stdout, "isatty", return_value=True),
            ):
                selected = engine._select_plan_projects(route, [])

            self.assertEqual([ctx.name for ctx in selected], ["feature_task-1"])
            self.assertEqual(sync_calls, [])
            self.assertEqual(save_calls, [])
            self.assertFalse((repo / "trees" / "feature_task" / "1").exists())
            result = orchestrator.last_plan_selection_result()
            self.assertEqual([worktree.name for worktree in result.created_worktrees], ["feature_task-1"])

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
            self.assertEqual(
                (repo / "trees" / "implementations_task" / "1" / "MAIN_TASK.md").read_text(encoding="utf-8"),
                "# task\n",
            )
            self.assertEqual(
                (repo / "trees" / "implementations_task" / "2" / "MAIN_TASK.md").read_text(encoding="utf-8"),
                "# task\n",
            )

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

            engine = self._runtime(repo, runtime, env={"ENVCTL_UI_SPINNER_MODE": "off"})
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

    def test_plan_selection_hyperlinks_plan_file_messages_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            plan_file = repo / "todo" / "plans" / "implementations" / "task.md"
            plan_file.write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(
                repo,
                runtime,
                env={"ENVCTL_UI_SPINNER_MODE": "off", "ENVCTL_UI_HYPERLINK_MODE": "on"},
            )
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001
            out = _TtyStringIO()
            with redirect_stdout(out):
                synced, error = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                    plan_counts={"implementations/task.md": 0},
                    raw_projects=raw_projects,
                    keep_plan=False,
                )

            self.assertIsNone(error)
            self.assertEqual(synced, [])
            rendered = out.getvalue()
            self.assertIn("\x1b]8;;file://", rendered)
            visible = strip_ansi(rendered)
            self.assertIn("Blasted and deleted 1 worktree(s) for implementations/task.md.", visible)
            self.assertIn("Moved implementations/task.md to done/implementations/task.md.", visible)

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

    def test_setup_worktree_creation_writes_provenance_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "venv").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / ".env").write_text("ENVIRONMENT=development\n", encoding="utf-8")
            (repo / "frontend" / "node_modules").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text('project_name: "repo"\n', encoding="utf-8")
            (repo / ".serena" / ".gitignore").write_text("memories/\n", encoding="utf-8")
            (repo / ".cgcignore").write_text(".git/\n", encoding="utf-8")

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_CGC_INDEX": "false"})

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    index = self._worktree_add_index(command)
                    self._assert_hooks_disabled_for_worktree_add(command)
                    self.assertEqual(command[index + 2], "-b")
                    self.assertEqual(command[index + 3], "feature-a-1")
                    self.assertEqual(command[index + 5], "origin/dev")
                    target = Path(command[index + 4])
                    target.mkdir(parents=True, exist_ok=True)
                    (target / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertTrue((repo / "trees" / "feature-a" / "1" / "backend" / "venv").is_symlink())
            self.assertEqual(
                (repo / "trees" / "feature-a" / "1" / "backend" / "venv").resolve(),
                (repo / "backend" / "venv").resolve(),
            )
            self.assertTrue((repo / "trees" / "feature-a" / "1" / "backend" / ".env").is_symlink())
            self.assertTrue((repo / "trees" / "feature-a" / "1" / "frontend" / "node_modules").is_symlink())
            self.assertEqual(
                (repo / "trees" / "feature-a" / "1" / ".serena" / "project.yml").read_text(encoding="utf-8"),
                'project_name: "repo-feature-a-1"\n',
            )
            self.assertEqual(
                (repo / "trees" / "feature-a" / "1" / ".serena" / ".gitignore").read_text(encoding="utf-8"),
                "memories/\n",
            )
            self.assertEqual(
                (repo / "trees" / "feature-a" / "1" / ".cgcignore").read_text(encoding="utf-8"),
                ".git/\n",
            )
            provenance = self._read_provenance(repo / "trees" / "feature-a" / "1")
            self.assertEqual(provenance.get("source_branch"), "dev")
            self.assertEqual(provenance.get("source_ref"), "origin/dev")
            self.assertEqual(provenance.get("resolution_reason"), "attached_branch")
            metadata = json.loads(
                (repo / "trees" / "feature-a" / "1" / ".envctl-state" / "code-intelligence.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(metadata.get("schema_version"), 1)
            self.assertEqual(metadata.get("serena_project_name"), "repo-feature-a-1")
            self.assertEqual(metadata.get("cgc_context"), "Repo-feature-a-1")
            self.assertEqual(
                metadata.get("files"),
                {
                    ".serena/project.yml": True,
                    ".serena/.gitignore": True,
                    ".cgcignore": True,
                },
            )
            self.assertFalse(metadata.get("cgc_index_requested"))

    def test_setup_worktree_can_disable_code_intelligence_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text('project_name: "repo"\n', encoding="utf-8")

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_CODE_INTELLIGENCE": "off"})

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertFalse((target_root / ".serena" / "project.yml").exists())

    def test_setup_worktree_can_run_cgc_index_for_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".cgcignore").write_text(".git/\n", encoding="utf-8")
            cgc_calls: list[tuple[list[str], Path | None]] = []

            engine = self._runtime(
                repo,
                runtime,
                env={"ENVCTL_WORKTREE_CGC_INDEX": "true", "ENVCTL_WORKTREE_CGC_DATABASE": "kuzudb"},
            )

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = env, timeout
                command = [str(token) for token in cmd]
                if command[:3] == ["cgc", "context", "create"]:
                    cgc_calls.append((command, cwd))
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="created\n", stderr="")
                if command[:2] == ["cgc", "index"]:
                    cgc_calls.append((command, cwd))
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(len(cgc_calls), 2)
            self.assertEqual(
                cgc_calls[0][0],
                ["cgc", "context", "create", "Repo-feature-a-1", "--database", "kuzudb"],
            )
            self.assertEqual(cgc_calls[0][1].resolve() if cgc_calls[0][1] else None, target_root.resolve())
            self.assertEqual(cgc_calls[1][0][:3], ["cgc", "index", str(target_root.resolve())])
            self.assertEqual(cgc_calls[1][0][3:], ["--context", "Repo-feature-a-1"])
            self.assertEqual(cgc_calls[1][1].resolve() if cgc_calls[1][1] else None, target_root.resolve())
            metadata = json.loads((target_root / ".envctl-state" / "code-intelligence.json").read_text(encoding="utf-8"))
            self.assertTrue(metadata.get("cgc_index_requested"))
            self.assertTrue(metadata.get("cgc_context_created"))
            self.assertTrue(metadata.get("cgc_index_succeeded"))
            self.assertEqual(metadata.get("cgc_database"), "kuzudb")
            self.assertEqual(
                [item.get("command") for item in metadata.get("cgc_commands", [])],
                [
                    ["cgc", "context", "create", "Repo-feature-a-1", "--database", "kuzudb"],
                    ["cgc", "index", str(target_root.resolve()), "--context", "Repo-feature-a-1"],
                ],
            )

    def test_setup_worktree_rewrites_serena_project_name_and_preserves_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature.a/with spaces" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text(
                "project_name: envctl\n"
                "language: python\n"
                "ignored_paths:\n"
                "  - trees/**\n",
                encoding="utf-8",
            )

            engine = self._runtime(repo, runtime)

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature.a/with spaces", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(
                (target_root / ".serena" / "project.yml").read_text(encoding="utf-8"),
                "project_name: envctl-feature-a_with_spaces-1\n"
                "language: python\n"
                "ignored_paths:\n"
                "  - trees/**\n",
            )

    def test_setup_worktree_prepends_serena_project_name_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text("language: python\n", encoding="utf-8")

            engine = self._runtime(repo, runtime)

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(
                (target_root / ".serena" / "project.yml").read_text(encoding="utf-8"),
                "project_name: repo-feature-a-1\nlanguage: python\n",
            )

    def test_setup_worktree_code_intelligence_templates_override_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text("project_name: repo\n", encoding="utf-8")
            (repo / ".cgcignore").write_text(".git/\n", encoding="utf-8")

            engine = self._runtime(
                repo,
                runtime,
                env={
                    "ENVCTL_WORKTREE_CGC_CONTEXT_TEMPLATE": "ctx_{project}_{feature}_{iteration}",
                    "ENVCTL_WORKTREE_SERENA_PROJECT_TEMPLATE": "serena_{worktree}",
                    "ENVCTL_WORKTREE_CGC_INDEX": "true",
                },
            )
            cgc_calls: list[list[str]] = []

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[:3] == ["cgc", "context", "create"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[:2] == ["cgc", "index"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(
                (target_root / ".serena" / "project.yml").read_text(encoding="utf-8"),
                "project_name: serena_feature-a-1\n",
            )
            self.assertEqual(cgc_calls[0], ["cgc", "context", "create", "ctx_Repo_feature-a_1"])
            self.assertEqual(
                cgc_calls[1],
                ["cgc", "index", str(target_root.resolve()), "--context", "ctx_Repo_feature-a_1"],
            )

    def test_setup_worktree_forced_cgc_index_skips_when_cgc_is_not_installed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text('project_name: "repo"\n', encoding="utf-8")
            cgc_calls: list[list[str]] = []

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_CGC_INDEX": "true"})

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[:2] == ["cgc", "index"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=False):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(cgc_calls, [])
            self.assertEqual(
                (target_root / ".serena" / "project.yml").read_text(encoding="utf-8"),
                'project_name: "repo-feature-a-1"\n',
            )
            metadata = json.loads((target_root / ".envctl-state" / "code-intelligence.json").read_text(encoding="utf-8"))
            self.assertTrue(metadata.get("cgc_index_requested"))
            self.assertFalse(metadata.get("cgc_available"))

    def test_setup_worktree_cgc_launch_failure_does_not_fail_worktree_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            emitted: list[dict[str, object]] = []

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_CGC_INDEX": "true"})
            engine._emit = lambda event, **payload: emitted.append({"event": event, **payload})  # type: ignore[method-assign]

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[:3] == ["cgc", "context", "create"]:
                    raise FileNotFoundError("cgc")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertTrue(target_root.is_dir())
            self.assertTrue(
                any(
                    event.get("event") == "setup.worktree.code_intelligence.cgc_context"
                    and event.get("target") == str(target_root.resolve())
                    and event.get("context") == "Repo-feature-a-1"
                    and event.get("success") is False
                    and event.get("error") == "cgc"
                    for event in emitted
                )
            )

    def test_setup_worktree_existing_cgc_context_message_continues_to_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".cgcignore").write_text(".git/\n", encoding="utf-8")
            emitted: list[dict[str, object]] = []
            cgc_calls: list[list[str]] = []

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_CGC_INDEX": "true"})
            engine._emit = lambda event, **payload: emitted.append({"event": event, **payload})  # type: ignore[method-assign]

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[:3] == ["cgc", "context", "create"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="context already exists")
                if command[:2] == ["cgc", "index"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(len(cgc_calls), 2)
            self.assertTrue(
                any(
                    item.get("event") == "setup.worktree.code_intelligence.cgc_context"
                    and item.get("already_exists") is True
                    and item.get("success") is True
                    for item in emitted
                )
            )
            metadata = json.loads((target_root / ".envctl-state" / "code-intelligence.json").read_text(encoding="utf-8"))
            self.assertFalse(metadata.get("cgc_context_created"))
            self.assertTrue(metadata.get("cgc_context_already_exists"))
            self.assertTrue(metadata.get("cgc_index_succeeded"))

    def test_setup_worktree_cgc_context_failure_skips_index_but_preserves_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".cgcignore").write_text(".git/\n", encoding="utf-8")
            emitted: list[dict[str, object]] = []
            cgc_calls: list[list[str]] = []

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_CGC_INDEX": "true"})
            engine._emit = lambda event, **payload: emitted.append({"event": event, **payload})  # type: ignore[method-assign]

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[:3] == ["cgc", "context", "create"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=2, stdout="", stderr="database failed")
                if command[:2] == ["cgc", "index"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(cgc_calls, [["cgc", "context", "create", "Repo-feature-a-1"]])
            self.assertTrue(
                any(
                    item.get("event") == "setup.worktree.code_intelligence.cgc_context"
                    and item.get("success") is False
                    and item.get("returncode") == 2
                    and item.get("stderr") == "database failed"
                    for item in emitted
                )
            )
            metadata = json.loads((target_root / ".envctl-state" / "code-intelligence.json").read_text(encoding="utf-8"))
            self.assertFalse(metadata.get("cgc_index_succeeded"))
            self.assertEqual(metadata.get("cgc_context_returncode"), 2)

    def test_setup_worktree_without_serena_or_cgc_config_does_not_fail_or_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            cgc_calls: list[list[str]] = []

            engine = self._runtime(repo, runtime)

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[:2] == ["cgc", "index"]:
                    cgc_calls.append(command)
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertEqual(cgc_calls, [])
            self.assertFalse((target_root / ".serena").exists())
            self.assertFalse((target_root / ".cgcignore").exists())

    def test_setup_worktree_creation_can_inherit_git_hooks_by_policy(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_GIT_HOOKS": "inherit"})

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    self._worktree_add_index(command)
                    self._assert_hooks_inherited_for_worktree_add(command)
                    target = Path(command[-2])
                    target.mkdir(parents=True, exist_ok=True)
                    (target / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)

    def test_invalid_worktree_git_hooks_policy_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_GIT_HOOKS": "maybe"})

            with self.assertRaisesRegex(RuntimeError, "ENVCTL_WORKTREE_GIT_HOOKS"):
                engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

    def test_plan_sync_created_worktrees_write_provenance_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text('project_name: "repo"\n', encoding="utf-8")
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime)

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="release/2026.03\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/release/2026.03"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    index = self._worktree_add_index(command)
                    self._assert_hooks_disabled_for_worktree_add(command)
                    self.assertEqual(command[index + 2], "-b")
                    self.assertEqual(command[index + 3], "implementations_task-1")
                    self.assertEqual(command[index + 5], "origin/release/2026.03")
                    target = Path(command[index + 4])
                    target.mkdir(parents=True, exist_ok=True)
                    (target / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_feature_worktrees(  # noqa: SLF001
                feature="implementations_task",
                count=1,
                plan_file="implementations/task.md",
            )

            self.assertIsNone(error)
            provenance = self._read_provenance(repo / "trees" / "implementations_task" / "1")
            self.assertEqual(provenance.get("source_branch"), "release/2026.03")
            self.assertEqual(provenance.get("source_ref"), "origin/release/2026.03")
            self.assertEqual(provenance.get("plan_file"), "implementations/task.md")
            self.assertEqual(
                (repo / "trees" / "implementations_task" / "1" / ".serena" / "project.yml").read_text(
                    encoding="utf-8"
                ),
                'project_name: "repo-implementations_task-1"\n',
            )

    def test_setup_worktree_real_git_smoke_writes_isolated_code_intelligence(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            bin_dir = root / "bin"
            cgc_log = root / "cgc.log"
            repo.mkdir(parents=True, exist_ok=True)
            bin_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
            (repo / "README.md").write_text("# repo\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-q", "-m", "initial"], cwd=repo, check=True)
            (repo / ".serena").mkdir(parents=True, exist_ok=True)
            (repo / ".serena" / "project.yml").write_text("project_name: repo\nlanguage: python\n", encoding="utf-8")
            (repo / ".cgcignore").write_text(".git/\n", encoding="utf-8")
            cgc = bin_dir / "cgc"
            cgc.write_text(
                "#!/bin/sh\n"
                f"printf '%s\\n' \"$*\" >> {cgc_log}\n"
                "exit 0\n",
                encoding="utf-8",
            )
            cgc.chmod(0o755)

            env = {
                "ENVCTL_WORKTREE_CGC_INDEX": "true",
                "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            }
            engine = self._runtime(repo, runtime, env=env)

            with patch.object(PythonEngineRuntime, "_command_exists", return_value=True):
                error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            target = repo / "trees" / "feature-a" / "1"
            self.assertIsNone(error)
            self.assertTrue((target / ".git").exists())
            self.assertEqual(
                (target / ".serena" / "project.yml").read_text(encoding="utf-8"),
                "project_name: repo-feature-a-1\nlanguage: python\n",
            )
            self.assertEqual((target / ".cgcignore").read_text(encoding="utf-8"), ".git/\n")
            metadata = json.loads((target / ".envctl-state" / "code-intelligence.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata.get("serena_project_name"), "repo-feature-a-1")
            self.assertEqual(metadata.get("cgc_context"), "Repo-feature-a-1")
            self.assertTrue(metadata.get("cgc_index_succeeded"))
            self.assertEqual(
                cgc_log.read_text(encoding="utf-8").splitlines(),
                [
                    "context create Repo-feature-a-1",
                    f"index {target.resolve()} --context Repo-feature-a-1",
                ],
            )

    def test_setup_worktree_recovers_partial_git_worktree_after_late_hook_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "venv").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime)
            events: list[dict[str, object]] = []
            engine._emit = lambda event, **payload: events.append({"event": event, **payload})  # type: ignore[method-assign]

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/late-hook-failure\n", encoding="utf-8")
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=1,
                        stdout="",
                        stderr="post-checkout hook failed",
                    )
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertTrue((target_root / ".git").exists())
            self.assertTrue((target_root / "backend" / "venv").is_symlink())
            self.assertEqual(self._read_provenance(target_root).get("source_branch"), "dev")
            self.assertTrue(
                any(item.get("event") == "setup.worktree.partial_git_failure_recovered" for item in events)
            )

    def test_plan_sync_recovers_partial_git_worktree_without_advancing_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "implementations_task" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime)

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/late-hook-failure\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="hook failed")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            result = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 1},
                raw_projects=[],
                keep_plan=True,
            )

            self.assertIsNone(result.error)
            self.assertEqual([item.name for item in result.created_worktrees], ["implementations_task-1"])
            self.assertTrue((target_root / "MAIN_TASK.md").is_file())
            self.assertFalse((repo / "trees" / "implementations_task" / "2").exists())

    def test_hook_inheritance_surfaces_late_hook_failure_even_when_target_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_WORKTREE_GIT_HOOKS": "inherit"})

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    target_root.mkdir(parents=True, exist_ok=True)
                    (target_root / ".git").write_text("gitdir: /tmp/hook-failure\n", encoding="utf-8")
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=1,
                        stdout="",
                        stderr="post-checkout hook failed",
                    )
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNotNone(error)
            self.assertIn("post-checkout hook failed", error or "")

    def test_plan_sync_reports_created_worktree_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})

            result = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 2},
                raw_projects=[],
                keep_plan=True,
            )

            self.assertIsNone(result.error)
            self.assertEqual([item.name for item in result.created_worktrees], ["implementations_task-1", "implementations_task-2"])
            self.assertEqual(
                [item.root for item in result.created_worktrees],
                [
                    (repo / "trees" / "implementations_task" / "1").resolve(),
                    (repo / "trees" / "implementations_task" / "2").resolve(),
                ],
            )
            self.assertTrue((result.created_worktrees[0].root / "MAIN_TASK.md").is_file())
            self.assertEqual(result.created_worktrees[0].plan_file, "implementations/task.md")

    def test_plan_sync_reports_only_new_worktrees_as_launch_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001

            result = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                plan_counts={"implementations/task.md": 2},
                raw_projects=raw_projects,
                keep_plan=True,
            )

            self.assertIsNone(result.error)
            self.assertEqual(len(result.raw_projects), 2)
            self.assertEqual([item.name for item in result.created_worktrees], ["implementations_task-2"])

    def test_plan_selection_records_launch_candidates_for_startup_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})
            route = parse_route(["--plan", "implementations/task"], env={})

            selected = engine._select_plan_projects(route, [])

            selection_result = engine.planning_worktree_orchestrator.last_plan_selection_result()
            self.assertIsInstance(selection_result, PlanSelectionResult)
            self.assertEqual([ctx.name for ctx in selected], ["implementations_task-1"])
            self.assertEqual([item.name for item in selection_result.created_worktrees], ["implementations_task-1"])

    def test_plan_selection_with_new_session_launch_creates_and_targets_next_iteration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})
            contexts = engine._discover_projects(mode="trees")
            route = parse_route(
                ["--plan", "implementations/task", "--tmux", "--opencode", "--headless", "--tmux-new-session"],
                env={},
            )

            selected = engine._select_plan_projects(route, contexts)

            selection_result = engine.planning_worktree_orchestrator.last_plan_selection_result()
            self.assertEqual([ctx.name for ctx in selected], ["implementations_task-2"])
            self.assertEqual([item.name for item in selection_result.created_worktrees], ["implementations_task-2"])
            self.assertTrue((repo / "trees" / "implementations_task" / "1").is_dir())
            self.assertTrue((repo / "trees" / "implementations_task" / "2").is_dir())

    def test_fresh_ai_worktree_is_not_scaled_down_while_session_marker_active(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")
            for iteration in ("1", "2", "3"):
                worktree = repo / "trees" / "implementations_task" / iteration
                worktree.mkdir(parents=True, exist_ok=True)
                (worktree / ".git").write_text(f"gitdir: /tmp/worktree-{iteration}\n", encoding="utf-8")
            protected = repo / "trees" / "implementations_task" / "3"
            (protected / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (protected / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "plan_file": "implementations/task.md",
                        "created_for_fresh_ai_launch": True,
                        "fresh_ai_launch_status": "launching",
                        "launch_transport": "omx",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            engine = self._runtime(repo, runtime)
            events: list[dict[str, object]] = []
            engine._emit = lambda event, **payload: events.append({"event": event, **payload})  # type: ignore[method-assign]
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001

            def fake_delete_worktree_path(**kwargs):  # noqa: ANN001
                shutil.rmtree(Path(kwargs["worktree_root"]))

                class _Result:
                    success = True
                    message = ""

                return _Result()

            with patch("envctl_engine.planning.worktree_domain.delete_worktree_path", side_effect=fake_delete_worktree_path):
                result = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                    plan_counts={"implementations/task.md": 1},
                    raw_projects=raw_projects,
                    keep_plan=True,
                )

            self.assertIsNone(result.error)
            self.assertTrue(protected.is_dir())
            self.assertTrue(
                any(
                    event.get("event") == "planning.worktree.cleanup.skipped_active_ai_session"
                    and event.get("worktree") == "implementations_task-3"
                    for event in events
                )
            )

    def test_stale_fresh_ai_worktree_can_be_scaled_down_after_session_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")
            for iteration in ("1", "2"):
                worktree = repo / "trees" / "implementations_task" / iteration
                worktree.mkdir(parents=True, exist_ok=True)
                (worktree / ".git").write_text(f"gitdir: /tmp/worktree-{iteration}\n", encoding="utf-8")
            stale = repo / "trees" / "implementations_task" / "2"
            (stale / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (stale / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "plan_file": "implementations/task.md",
                        "created_for_fresh_ai_launch": True,
                        "fresh_ai_launch_status": "launched",
                        "launch_transport": "omx",
                        "session_name": "omx-missing-session",
                    }
                )
                + "\n",
                encoding="utf-8",
            )

            engine = self._runtime(repo, runtime)
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001

            def fake_delete_worktree_path(**kwargs):  # noqa: ANN001
                shutil.rmtree(Path(kwargs["worktree_root"]))

                class _Result:
                    success = True
                    message = ""

                return _Result()

            with patch("envctl_engine.planning.worktree_domain.delete_worktree_path", side_effect=fake_delete_worktree_path):
                result = engine._sync_plan_worktrees_from_plan_counts(  # noqa: SLF001
                    plan_counts={"implementations/task.md": 1},
                    raw_projects=raw_projects,
                    keep_plan=True,
                )

            self.assertIsNone(result.error)
            self.assertFalse(stale.exists())

    def test_setup_worktree_creation_resets_existing_branch_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime)

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "refs/heads/feature-a-1"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="abc123\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    index = self._worktree_add_index(command)
                    self._assert_hooks_disabled_for_worktree_add(command)
                    self.assertEqual(command[index + 2], "-B")
                    self.assertEqual(command[index + 3], "feature-a-1")
                    self.assertEqual(command[index + 5], "origin/dev")
                    target = Path(command[index + 4])
                    target.mkdir(parents=True, exist_ok=True)
                    (target / ".git").write_text("gitdir: /tmp/worktree-1\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)

    def test_setup_worktree_recreate_overwrites_existing_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (target_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (target_root / ".git").write_text("gitdir: /tmp/existing-worktree\n", encoding="utf-8")
            (target_root / ".envctl-state" / "worktree-provenance.json").write_text(
                '{"schema_version": 1, "source_branch": "old-base", "source_ref": "origin/old-base"}\n',
                encoding="utf-8",
            )

            engine = self._runtime(repo, runtime)
            contexts = engine._discover_projects(mode="main")

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="new-base\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/new-base"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    index = self._worktree_add_index(command)
                    self._assert_hooks_disabled_for_worktree_add(command)
                    self.assertEqual(command[index + 2], "-b")
                    self.assertEqual(command[index + 3], "feature-a-1")
                    self.assertEqual(command[index + 5], "origin/new-base")
                    target = Path(command[index + 4])
                    target.mkdir(parents=True, exist_ok=True)
                    (target / ".git").write_text("gitdir: /tmp/recreated-worktree\n", encoding="utf-8")
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            def fake_delete_worktree_path(**_kwargs):  # noqa: ANN001
                shutil.rmtree(target_root)

                class _Result:
                    success = True
                    message = ""

                return _Result()

            engine.process_runner.run = fake_run  # type: ignore[method-assign]
            route = parse_route(["--setup-worktree", "feature-a", "1", "--setup-worktree-recreate"], env={})

            with patch("envctl_engine.planning.worktree_domain.delete_worktree_path", side_effect=fake_delete_worktree_path):
                selected = engine._apply_setup_worktree_selection(route, contexts)  # noqa: SLF001

            self.assertTrue(selected)
            provenance = self._read_provenance(target_root)
            self.assertEqual(provenance.get("source_branch"), "new-base")
            self.assertEqual(provenance.get("source_ref"), "origin/new-base")

    def test_setup_worktree_existing_preserves_existing_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend").mkdir(parents=True, exist_ok=True)
            (repo / "frontend").mkdir(parents=True, exist_ok=True)
            (target_root / ".envctl-state").mkdir(parents=True, exist_ok=True)
            (target_root / ".git").write_text("gitdir: /tmp/existing-worktree\n", encoding="utf-8")
            existing_payload = {
                "schema_version": 1,
                "source_branch": "saved-base",
                "source_ref": "origin/saved-base",
                "resolution_reason": "attached_branch",
            }
            (target_root / ".envctl-state" / "worktree-provenance.json").write_text(
                json.dumps(existing_payload) + "\n",
                encoding="utf-8",
            )

            engine = self._runtime(repo, runtime)
            contexts = engine._discover_projects(mode="main")
            route = parse_route(["--setup-worktree", "feature-a", "1", "--setup-worktree-existing"], env={})

            with patch.object(engine, "_create_single_worktree", side_effect=AssertionError("should not recreate")):
                selected = engine._apply_setup_worktree_selection(route, contexts)  # noqa: SLF001

            self.assertTrue(selected)
            self.assertEqual(self._read_provenance(target_root), existing_payload)

    def test_setup_worktree_placeholder_fallback_does_not_write_provenance(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            target_root = repo / "trees" / "feature-a" / "1"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / "venv").mkdir(parents=True, exist_ok=True)
            (repo / "backend" / ".env").write_text("ENVIRONMENT=development\n", encoding="utf-8")
            (repo / "frontend" / "node_modules").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_SETUP_WORKTREE_PLACEHOLDER_FALLBACK": "true"})

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                if command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    index = self._worktree_add_index(command)
                    self._assert_hooks_disabled_for_worktree_add(command)
                    self.assertEqual(command[index + 2], "-b")
                    self.assertEqual(command[index + 3], "feature-a-1")
                    self.assertEqual(command[index + 5], "origin/dev")
                    return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="git failure")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected")

            engine.process_runner.run = fake_run  # type: ignore[method-assign]

            error = engine._create_single_worktree(feature="feature-a", iteration="1")  # noqa: SLF001

            self.assertIsNone(error)
            self.assertTrue((target_root / ".envctl_worktree_placeholder").is_file())
            self.assertFalse((target_root / ".envctl-state" / "worktree-provenance.json").exists())
            self.assertTrue((target_root / "backend" / "venv").is_symlink())
            self.assertTrue((target_root / "backend" / ".env").is_symlink())
            self.assertTrue((target_root / "frontend" / "node_modules").is_symlink())

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

    def test_sync_plan_worktrees_hyperlinks_plan_file_in_spinner_updates_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")
            (repo / "trees" / "implementations_task" / "1").mkdir(parents=True, exist_ok=True)

            engine = self._runtime(repo, runtime, env={"ENVCTL_UI_HYPERLINK_MODE": "on"})
            update_messages: list[str] = []
            lifecycle_messages: list[str] = []

            @contextmanager
            def fake_spinner(message: str, *, enabled: bool, start_immediately: bool = True):
                _ = message, enabled, start_immediately

                class _SpinnerStub:
                    def start(self) -> None:
                        return None

                    def update(self, message: str) -> None:
                        update_messages.append(message)

                    def succeed(self, _message: str) -> None:
                        return None

                    def fail(self, _message: str) -> None:
                        return None

                yield _SpinnerStub()

            def capture_emit(event: str, **payload: object) -> None:
                if event == "ui.spinner.lifecycle" and payload.get("state") == "update":
                    lifecycle_messages.append(str(payload.get("message", "")))

            engine._emit = capture_emit  # type: ignore[method-assign]
            raw_projects = [(ctx.name, ctx.root) for ctx in engine._discover_projects(mode="trees")]  # noqa: SLF001

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
                    plan_counts={"implementations/task.md": 0},
                    raw_projects=raw_projects,
                    keep_plan=False,
                )

            self.assertIsNone(error)
            self.assertEqual(synced, [])
            self.assertTrue(any("\x1b]8;;file://" in message for message in update_messages))
            self.assertTrue(
                any("implementations/task.md" in strip_ansi(message) for message in update_messages)
            )
            self.assertTrue(any("\x1b]8;;file://" not in message for message in lifecycle_messages))
            self.assertTrue(any("implementations/task.md" in message for message in lifecycle_messages))


if __name__ == "__main__":
    unittest.main()
