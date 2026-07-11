# ruff: noqa: F403,F405
from __future__ import annotations

from envctl_engine.actions.action_git_state_support import ExistingPullRequest
from tests.python.actions.actions_cli_test_support import *  # noqa: F403,F405


class ActionsCliShipTests(unittest.TestCase):
    def test_partition_envctl_protected_paths_separates_staged_skipped_and_stageable_paths(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")

        partition = domain._partition_envctl_protected_paths(
            "A  MAIN_TASK.md\n"
            "?? .envctl-commit-message.md\n"
            " M .envctl-state/run.json\n"
            "?? OLD_TASK_1.md\n"
            "A  docs/OLD_TASK_archived.md\n"
            "?? trees/feature/1/file.py\n"
            "?? trees-feature/file.py\n"
            "M  app.py\n"
            " M docs/reference/commands.md\n"
            "R  old_name.py -> new_name.py\n"
        )

        self.assertEqual(partition.protected_staged_paths, ["MAIN_TASK.md", "docs/OLD_TASK_archived.md"])
        self.assertEqual(
            partition.protected_skipped_paths,
            [
                ".envctl-commit-message.md",
                ".envctl-state/run.json",
                "OLD_TASK_1.md",
                "trees/feature/1/file.py",
                "trees-feature/file.py",
            ],
        )
        self.assertEqual(partition.stageable_paths, ["app.py", "docs/reference/commands.md", "new_name.py"])

    def test_ship_action_reuses_commit_and_pr_then_reports_passed_checks_json(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            context = domain.ActionProjectContext(
                repo_root=repo_root,
                project_root=repo_root,
                project_name="Main",
                env={"ENVCTL_ACTION_JSON": "true"},
            )

            head_sha = {"value": "abc123"}
            git_outputs: dict[tuple[str, ...], str] = {
                ("rev-parse", "--abbrev-ref", "HEAD"): "feature/demo\n",
                ("status", "--porcelain", "--untracked-files=all"): (
                    "?? app.py\n"
                    "?? .envctl-commit-message.md\n"
                    "?? MAIN_TASK.md\n"
                    "?? OLD_TASK_1.md\n"
                    "?? .envctl-state/run.json\n"
                    "?? trees/feature/1/file.py\n"
                    "?? trees-feature/file.py\n"
                ),
            }

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "HEAD"]:
                    return f"{head_sha['value']}\n"
                return git_outputs.get(tuple(args), "")

            def fake_commit_action(_context: object) -> int:
                head_sha["value"] = "def456"
                return 0

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/gh"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch(
                    "envctl_engine.actions.project_action_domain.run_commit_action",
                    side_effect=fake_commit_action,
                ) as commit_action,
                patch("envctl_engine.actions.project_action_domain.run_pr_action", return_value=0) as pr_action,
                patch("envctl_engine.actions.project_action_domain.add_ship_pr_label", return_value=0) as label_pr,
                patch(
                    "envctl_engine.actions.project_action_domain.existing_pr_url",
                    return_value="https://github.com/acme/repo/pull/7",
                ),
                patch(
                    "envctl_engine.actions.project_action_domain.existing_pull_request",
                    side_effect=[
                        None,
                        ExistingPullRequest("https://github.com/acme/repo/pull/7", "main"),
                    ],
                ),
                patch(
                    "envctl_engine.actions.project_action_domain._github_pr_checks",
                    return_value={
                        "state": "checks_passed",
                        "passed_checks": [{"name": "pytest", "workflow": "Tests", "state": "SUCCESS"}],
                        "failing_checks": [],
                        "pending_checks": [],
                        "pr_checks": [
                            {"name": "pytest", "workflow": "Tests", "state": "SUCCESS"},
                            {"name": "preview", "workflow": "Deploy", "state": "NEUTRAL"},
                        ],
                        "deployment_url": "https://preview.test/pr-7",
                        "duration_seconds": 0.1,
                    },
                ),
                redirect_stdout(StringIO()) as stdout,
            ):
                code = domain.run_ship_action(context)

        self.assertEqual(code, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "checks_passed")
        self.assertEqual(payload["branch"], "feature/demo")
        self.assertEqual(payload["pr_url"], "https://github.com/acme/repo/pull/7")
        self.assertTrue(payload["committed"])
        self.assertEqual(payload["commit_sha"], "def456")
        self.assertTrue(payload["pr_created"])
        self.assertEqual(payload["passed_checks"], [{"name": "pytest", "workflow": "Tests", "state": "SUCCESS"}])
        self.assertEqual(
            payload["pr_checks"],
            [
                {"name": "pytest", "workflow": "Tests", "state": "SUCCESS"},
                {"name": "preview", "workflow": "Deploy", "state": "NEUTRAL"},
            ],
        )
        self.assertEqual(payload["deployment_url"], "https://preview.test/pr-7")
        self.assertEqual(payload["step_statuses"], ["committed_pushed", "pr_created", "checks_passed"])
        self.assertEqual(
            payload["protected_local_artifacts_skipped"],
            [
                ".envctl-commit-message.md",
                "MAIN_TASK.md",
                "OLD_TASK_1.md",
                ".envctl-state/run.json",
                "trees/feature/1/file.py",
                "trees-feature/file.py",
            ],
        )
        commit_action.assert_called_once_with(context)
        pr_action.assert_called_once_with(context)
        label_pr.assert_called_once_with(context, repo_root, "https://github.com/acme/repo/pull/7")

    def test_ship_action_reports_existing_pr_and_failed_checks(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            context = domain.ActionProjectContext(
                repo_root=repo_root,
                project_root=repo_root,
                project_name="Main",
                env={"ENVCTL_ACTION_JSON": "true"},
            )

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/demo\n"
                if args == ["rev-parse", "HEAD"]:
                    return "abc123\n"
                return ""

            def fake_run_git(_git_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
                if args == ["rev-parse", "--verify", "@{u}"]:
                    return subprocess.CompletedProcess(args, 0, stdout="abc123\n", stderr="")
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/gh"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
                patch("envctl_engine.actions.project_action_domain.run_commit_action", return_value=0) as commit_action,
                patch("envctl_engine.actions.project_action_domain.run_pr_action", return_value=0) as pr_action,
                patch("envctl_engine.actions.project_action_domain.add_ship_pr_label", return_value=0) as label_pr,
                patch(
                    "envctl_engine.actions.project_action_domain.existing_pr_url",
                    return_value="https://github.com/acme/repo/pull/7",
                ),
                patch(
                    "envctl_engine.actions.project_action_domain.existing_pull_request",
                    return_value=ExistingPullRequest("https://github.com/acme/repo/pull/7", "main"),
                ),
                patch(
                    "envctl_engine.actions.project_action_domain._github_pr_checks",
                    return_value={
                        "state": "checks_failed",
                        "failing_checks": [{"name": "pytest", "state": "FAILURE"}],
                        "pending_checks": [],
                        "duration_seconds": 0.1,
                    },
                ),
                redirect_stdout(StringIO()) as stdout,
            ):
                code = domain.run_ship_action(context)

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "checks_failed")
        self.assertFalse(payload["pr_created"])
        self.assertEqual(payload["step_statuses"], ["clean_no_changes", "pr_exists", "checks_failed"])
        commit_action.assert_called_once_with(context)
        pr_action.assert_not_called()
        label_pr.assert_called_once_with(context, repo_root, "https://github.com/acme/repo/pull/7")

    def test_ship_action_reports_predicted_merge_conflicts_json(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            context = domain.ActionProjectContext(
                repo_root=repo_root,
                project_root=repo_root,
                project_name="Main",
                env={"ENVCTL_ACTION_JSON": "true"},
            )

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/demo\n"
                if args == ["rev-parse", "HEAD"]:
                    return "abc123\n"
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return ""
                if args == ["diff", "--name-only", "--diff-filter=U"]:
                    return ""
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "base123\n"
                if args == ["merge-base", "HEAD", "origin/main"]:
                    return "mbase123\n"
                return ""

            def fake_run(git_root: Path, args: list[str]):  # noqa: ANN001
                if args == ["merge-tree", "--write-tree", "--messages", "--name-only", "HEAD", "origin/main"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=1,
                        stdout=(
                            "tree123\n"
                            "python/app.py\n"
                            "\n"
                            "Auto-merging python/app.py\n"
                            "CONFLICT (content): Merge conflict in python/app.py\n"
                        ),
                        stderr="",
                    )
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run),
                patch("envctl_engine.actions.project_action_domain.run_commit_action", return_value=0) as commit_action,
                patch("envctl_engine.actions.project_action_domain.add_ship_pr_label", return_value=0) as label_pr,
                patch(
                    "envctl_engine.actions.project_action_domain.existing_pr_url",
                    return_value="https://github.com/acme/repo/pull/7",
                ),
                patch(
                    "envctl_engine.actions.project_action_domain.existing_pull_request",
                    return_value=ExistingPullRequest("https://github.com/acme/repo/pull/7", "main"),
                ),
                redirect_stdout(StringIO()) as stdout,
            ):
                code = domain.run_ship_action(context)

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "merge_conflicts")
        self.assertEqual(payload["checks_state"], "merge_conflicts")
        self.assertEqual(payload["step_statuses"], ["clean_no_changes", "pr_exists", "merge_conflicts"])
        self.assertEqual(payload["merge_conflicts"]["state"], "conflicts")
        self.assertEqual(payload["merge_conflicts"]["base_ref"], "origin/main")
        self.assertEqual(payload["merge_conflicts"]["head_ref"], "HEAD")
        self.assertEqual(payload["merge_conflicts"]["merge_base"], "mbase123")
        self.assertEqual(payload["merge_conflicts"]["conflicting_files"][0]["path"], "python/app.py")
        self.assertIn("CONFLICT (content)", payload["merge_conflicts"]["conflicting_files"][0]["messages"][0])
        self.assertIn("git merge origin/main", payload["merge_conflicts"]["resolution_steps"])
        commit_action.assert_called_once_with(context)
        label_pr.assert_called_once_with(context, repo_root, "https://github.com/acme/repo/pull/7")

    def test_ship_action_reports_existing_unmerged_index_conflicts_before_commit(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            context = domain.ActionProjectContext(
                repo_root=repo_root,
                project_root=repo_root,
                project_name="Main",
                env={"ENVCTL_ACTION_JSON": "true"},
            )

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/demo\n"
                if args == ["rev-parse", "HEAD"]:
                    return "abc123\n"
                if args == ["diff", "--name-only", "--diff-filter=U"]:
                    return "src/service.py\n"
                if args == ["ls-files", "-u"]:
                    return "100644 aaa 1\tsrc/service.py\n100644 bbb 2\tsrc/service.py\n100644 ccc 3\tsrc/service.py\n"
                return ""

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.run_commit_action", return_value=0) as commit_action,
                redirect_stdout(StringIO()) as stdout,
            ):
                code = domain.run_ship_action(context)

        self.assertEqual(code, 1)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "merge_conflicts")
        self.assertEqual(payload["step_statuses"], ["merge_conflicts"])
        self.assertEqual(payload["merge_conflicts"]["state"], "conflicts")
        self.assertEqual(payload["merge_conflicts"]["type"], "unmerged_index")
        self.assertEqual(payload["merge_conflicts"]["conflicting_files"][0]["stages"], ["1", "2", "3"])
        self.assertEqual(
            payload["operation_statuses"],
            {
                "checks": "not_run",
                "commit": "not_run",
                "merge_conflicts": "conflicts",
                "pr": "not_run",
                "push": "not_run",
            },
        )
        commit_action.assert_not_called()

    def test_probe_dirty_worktree_classifies_porcelain_status(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            project_root = repo_root / "trees" / "feature-a" / "1"
            project_root.mkdir(parents=True, exist_ok=True)

            cases = {
                "clean": ("", (False, False, False)),
                "staged": ("M  app.py\n", (True, False, False)),
                "unstaged": (" M app.py\n", (False, True, False)),
                "untracked": ("?? new.py\n", (False, False, True)),
                "mixed": ("MM app.py\n?? new.py\n", (True, True, True)),
            }

            for label, (status_output, expected) in cases.items():
                with self.subTest(label=label):
                    with patch(
                        "envctl_engine.actions.project_action_domain._git_output",
                        return_value=status_output,
                    ) as git_output:
                        report = domain.probe_dirty_worktree(project_root, repo_root, project_name="feature-a-1")
                    git_output.assert_called_once_with(
                        project_root,
                        ["status", "--porcelain", "--untracked-files=all"],
                    )
                    self.assertEqual((report.staged, report.unstaged, report.untracked), expected)
                    self.assertEqual(report.project_name, "feature-a-1")

    def test_existing_pr_url_ignores_closed_prs(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            git_root = Path(tmpdir)

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                self.assertIn("--state", args)
                self.assertIn("open", args)
                return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/gh"),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                url = domain.existing_pr_url(git_root, "dev")

        self.assertEqual(url, "")
