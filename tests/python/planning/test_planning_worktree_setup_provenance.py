# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.planning_worktree_setup_test_support import *


class PlanningWorktreeSetupProvenanceTests(PlanningWorktreeSetupTestCase):
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
                'project_name: "repo"\n',
            )
            self.assertEqual(
                (repo / "trees" / "feature-a" / "1" / ".serena" / "project.local.yml").read_text(
                    encoding="utf-8"
                ),
                'project_name: "repo-feature-a-1"\n',
            )
            self.assertEqual(
                (repo / "trees" / "feature-a" / "1" / ".serena" / ".gitignore").read_text(encoding="utf-8"),
                "memories/\n",
            )
            self.assertFalse((repo / "trees" / "feature-a" / "1" / ".cgcignore").exists())
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
                    ".serena/project.local.yml": True,
                    ".serena/.gitignore": True,
                    ".cgcignore": False,
                    ".codegraph/.gitignore": False,
                    ".codegraph/codegraph.db": False,
                },
            )
            self.assertFalse(metadata.get("cgc_index_requested"))
            self.assertEqual(metadata.get("cgc_index_skipped_reason"), "disabled")

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
                    return subprocess.CompletedProcess(
                        args=command, returncode=0, stdout="release/2026.03\n", stderr=""
                    )
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
                (repo / "trees" / "implementations_task" / "1" / ".serena" / "project.yml").read_text(encoding="utf-8"),
                'project_name: "repo"\n',
            )
            self.assertEqual(
                (repo / "trees" / "implementations_task" / "1" / ".serena" / "project.local.yml").read_text(
                    encoding="utf-8"
                ),
                'project_name: "repo-implementations_task-1"\n',
            )

    def test_plan_sync_prefers_invocation_worktree_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            invocation = repo / "trees" / "current" / "1"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            invocation.mkdir(parents=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime, env={"ENVCTL_INVOCATION_CWD": str(invocation)})

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                git_cwd = command[2]
                if git_cwd == str(invocation.resolve()) and command[3:] == ["rev-parse", "--show-toplevel"]:
                    return subprocess.CompletedProcess(
                        args=command, returncode=0, stdout=f"{invocation.resolve()}\n", stderr=""
                    )
                if git_cwd == str(repo.resolve()) and command[3:] == ["rev-parse", "--git-common-dir"]:
                    return subprocess.CompletedProcess(
                        args=command, returncode=0, stdout=f"{repo / '.git'}\n", stderr=""
                    )
                if git_cwd == str(invocation.resolve()) and command[3:] == ["rev-parse", "--git-common-dir"]:
                    return subprocess.CompletedProcess(
                        args=command, returncode=0, stdout=f"{repo / '.git'}\n", stderr=""
                    )
                if git_cwd == str(invocation.resolve()) and command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(
                        args=command, returncode=0, stdout="feature/current\n", stderr=""
                    )
                if git_cwd == str(repo.resolve()) and command[3:] == [
                    "rev-parse",
                    "--verify",
                    "origin/feature/current",
                ]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    index = self._worktree_add_index(command)
                    self.assertEqual(command[index + 5], "origin/feature/current")
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
            self.assertEqual(provenance.get("source_branch"), "feature/current")
            self.assertEqual(provenance.get("source_ref"), "origin/feature/current")
            self.assertEqual(provenance.get("resolution_reason"), "invocation_worktree_branch")

    def test_plan_sync_ignores_invocation_checkout_from_different_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            repo = root / "repo"
            unrelated = root / "unrelated"
            runtime = root / "runtime"
            (repo / ".git").mkdir(parents=True, exist_ok=True)
            (unrelated / ".git").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations").mkdir(parents=True, exist_ok=True)
            (repo / "todo" / "plans" / "implementations" / "task.md").write_text("# task\n", encoding="utf-8")

            engine = self._runtime(repo, runtime, env={"ENVCTL_INVOCATION_CWD": str(unrelated)})

            def fake_run(cmd, *, cwd=None, env=None, timeout=None):  # noqa: ANN001
                _ = cwd, env, timeout
                command = [str(token) for token in cmd]
                git_cwd = command[2]
                if git_cwd == str(unrelated.resolve()) and command[3:] == ["rev-parse", "--show-toplevel"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout=f"{unrelated}\n", stderr="")
                if git_cwd == str(repo.resolve()) and command[3:] == ["rev-parse", "--git-common-dir"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout=f"{repo / '.git'}\n", stderr="")
                if git_cwd == str(unrelated.resolve()) and command[3:] == ["rev-parse", "--git-common-dir"]:
                    return subprocess.CompletedProcess(
                        args=command, returncode=0, stdout=f"{unrelated / '.git'}\n", stderr=""
                    )
                if git_cwd == str(unrelated.resolve()) and command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    raise AssertionError("unrelated checkout branch should not be used")
                if git_cwd == str(repo.resolve()) and command[3:] == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="dev\n", stderr="")
                if git_cwd == str(repo.resolve()) and command[3:] == ["rev-parse", "--verify", "origin/dev"]:
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="deadbeef\n", stderr="")
                if "worktree" in command:
                    index = self._worktree_add_index(command)
                    self.assertEqual(command[index + 5], "origin/dev")
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
            self.assertEqual(provenance.get("source_branch"), "dev")
            self.assertEqual(provenance.get("source_ref"), "origin/dev")
            self.assertEqual(provenance.get("resolution_reason"), "attached_branch")

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

            with patch(
                "envctl_engine.planning.worktree_domain.delete_worktree_path", side_effect=fake_delete_worktree_path
            ):
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
