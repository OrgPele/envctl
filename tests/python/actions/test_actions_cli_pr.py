# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.actions.actions_cli_test_support import *  # noqa: F403,F405
from envctl_engine.actions.action_git_state_support import ExistingPullRequest


class ActionsCliPrTests(unittest.TestCase):
    def test_pr_action_reports_existing_pr_and_skips_create(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            calls: list[list[str]] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/demo\n"
                if args and args[0:2] == ["log", "--oneline"]:
                    return "abc123 feat: demo\n"
                if args == ["status", "--porcelain"]:
                    return ""
                return ""

            def fake_which(name: str) -> str | None:
                if name == "git":
                    return f"/usr/bin/{name}"
                return None

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                calls.append(command)
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected command")

            with (
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch(
                    "envctl_engine.actions.project_action_domain.existing_pull_request",
                    return_value=ExistingPullRequest(
                        url="https://github.com/acme/supportopia/pull/42",
                        base_branch="main",
                    ),
                ),
                patch("envctl_engine.actions.project_action_domain.shutil.which", side_effect=fake_which),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_pr_action(repo_root, repo_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("PR already exists: https://github.com/acme/supportopia/pull/42", output)
            self.assertEqual(calls, [])

    def test_pr_action_commits_and_pushes_dirty_worktree_before_creating_pr(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            calls: list[list[str]] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/dirty-pr\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["merge-base", "feature/dirty-pr", "origin/main"]:
                    return "mbase123\n"
                if args == ["log", "-1", "--pretty=%s"]:
                    return "feat: dirty branch\n"
                if args == [
                    "log",
                    "--reverse",
                    "--no-merges",
                    "--format=%h%x1f%s%x1f%b%x1e",
                    "mbase123..feature/dirty-pr",
                ]:
                    return "abc123\x1ffeat: dirty branch\x1f\x1e"
                return ""

            def fake_which(name: str) -> str | None:
                if name in {"git", "gh"}:
                    return f"/usr/bin/{name}"
                return None

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                calls.append(command)
                if command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"]:
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=0,
                        stdout="https://github.com/acme/supportopia/pull/104\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected command")

            with (
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.existing_pull_request", return_value=None),
                patch("envctl_engine.actions.project_action_domain.probe_dirty_worktree") as dirty_probe,
                patch("envctl_engine.actions.project_action_domain.run_commit_action", return_value=0) as commit_action,
                patch("envctl_engine.actions.project_action_domain.shutil.which", side_effect=fake_which),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                dirty_probe.return_value = domain.DirtyWorktreeReport(
                    project_name="Main",
                    project_root=repo_root,
                    git_root=repo_root,
                    staged=False,
                    unstaged=True,
                    untracked=False,
                )
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_pr_action(repo_root, repo_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Dirty worktree detected for Main; committing and pushing before PR creation.", output)
            commit_action.assert_called_once()
            self.assertTrue(
                any(command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"] for command in calls), msg=calls
            )

    def test_pr_action_aborts_when_dirty_worktree_commit_fails(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            calls: list[list[str]] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/dirty-pr\n"
                return ""

            def fake_which(name: str) -> str | None:
                if name in {"git", "gh"}:
                    return f"/usr/bin/{name}"
                return None

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                calls.append(command)
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected command")

            with (
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.existing_pull_request", return_value=None),
                patch("envctl_engine.actions.project_action_domain.probe_dirty_worktree") as dirty_probe,
                patch("envctl_engine.actions.project_action_domain.run_commit_action", return_value=1) as commit_action,
                patch("envctl_engine.actions.project_action_domain.shutil.which", side_effect=fake_which),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                dirty_probe.return_value = domain.DirtyWorktreeReport(
                    project_name="Main",
                    project_root=repo_root,
                    git_root=repo_root,
                    staged=True,
                    unstaged=True,
                    untracked=True,
                )
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_pr_action(repo_root, repo_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 1)
            self.assertIn("Dirty worktree detected for Main; committing and pushing before PR creation.", output)
            commit_action.assert_called_once()
            self.assertEqual(calls, [])

    def test_pr_action_create_path_runs_gh_by_default_when_no_existing_pr(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            calls: list[list[str]] = []
            captured_body: list[str] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/new-demo\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["merge-base", "feature/new-demo", "origin/main"]:
                    return "mbase123\n"
                if args == ["log", "-1", "--pretty=%s"]:
                    return "feat: add bounded pr body\n"
                if args == [
                    "log",
                    "--reverse",
                    "--no-merges",
                    "--format=%h%x1f%s%x1f%b%x1e",
                    "mbase123..feature/new-demo",
                ]:
                    return "abc123\x1ffeat: demo\x1ffirst body line\nsecond body line\x1e"
                if args == ["status", "--porcelain"]:
                    return ""
                if args == ["diff", "--stat", "origin/main...feature/new-demo"]:
                    return " foo.py | 2 +-\n 1 file changed, 1 insertion(+), 1 deletion(-)\n"
                return ""

            def fake_which(name: str) -> str | None:
                if name in {"git", "gh"}:
                    return f"/usr/bin/{name}"
                return None

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                calls.append(command)
                if command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"]:
                    body_file = Path(command[command.index("--body-file") + 1])
                    captured_body.append(body_file.read_text(encoding="utf-8"))
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=0,
                        stdout="https://github.com/acme/supportopia/pull/99\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected command")

            with (
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.existing_pull_request", return_value=None),
                patch("envctl_engine.actions.project_action_domain.shutil.which", side_effect=fake_which),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_pr_action(repo_root, repo_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertNotIn("PR already exists:", output)
            self.assertIn("https://github.com/acme/supportopia/pull/99", output)
            self.assertTrue(
                any(command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"] for command in calls), msg=calls
            )
            gh_create = next(
                command for command in calls if command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"]
            )
            self.assertNotIn("--fill", gh_create)
            self.assertIn("--title", gh_create)
            self.assertIn("feat: add bounded pr body", gh_create)
            self.assertIn("--body-file", gh_create)
            self.assertIn("--head", gh_create)
            self.assertIn("feature/new-demo", gh_create)
            self.assertIn("--base", gh_create)
            self.assertIn("main", gh_create)
            self.assertEqual(len(captured_body), 1)
            self.assertIn("- feat: demo (abc123)", captured_body[0])
            self.assertIn("first body line", captured_body[0])
            self.assertNotIn("Project: Main", captured_body[0])
            self.assertNotIn("## Commits", captured_body[0])
            self.assertLessEqual(len(captured_body[0]), domain.PR_BODY_MAX_CHARS)

    def test_pr_action_prefers_main_task_h1_for_title(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            (repo_root / "MAIN_TASK.md").write_text("# Envctl `--version` Flag Plan\n\nDetails\n", encoding="utf-8")
            calls: list[list[str]] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/title-from-task\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["merge-base", "feature/title-from-task", "origin/main"]:
                    return "mbase123\n"
                if args == ["log", "-1", "--pretty=%s"]:
                    return "### Scope\n"
                if args == [
                    "log",
                    "--reverse",
                    "--no-merges",
                    "--format=%h%x1f%s%x1f%b%x1e",
                    "mbase123..feature/title-from-task",
                ]:
                    return "abc123\x1ffallback commit\x1ffallback body\x1e"
                return ""

            def fake_which(name: str) -> str | None:
                if name in {"git", "gh"}:
                    return f"/usr/bin/{name}"
                return None

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                calls.append(command)
                if command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"]:
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=0,
                        stdout="https://github.com/acme/supportopia/pull/101\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected command")

            with (
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.existing_pull_request", return_value=None),
                patch("envctl_engine.actions.project_action_domain.shutil.which", side_effect=fake_which),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                code = actions_cli._run_pr_action(repo_root, repo_root, "Main")

            self.assertEqual(code, 0)
            gh_create = next(
                command for command in calls if command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"]
            )
            self.assertIn("--title", gh_create)
            self.assertIn("Envctl --version Flag Plan", gh_create)
            self.assertNotIn("### Scope", gh_create)

    def test_pr_action_truncates_large_commit_messages_to_recent_content(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            captured_body: list[str] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/huge-pr\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["merge-base", "feature/huge-pr", "origin/main"]:
                    return "mbase123\n"
                if args == ["log", "-1", "--pretty=%s"]:
                    return "feat: huge commit history\n"
                if args == [
                    "log",
                    "--reverse",
                    "--no-merges",
                    "--format=%h%x1f%s%x1f%b%x1e",
                    "mbase123..feature/huge-pr",
                ]:
                    entries = []
                    for index in range(5000):
                        entries.append(f"{index:06x}\x1fcommit {index}\x1fbody line {index} " + ("x" * 40) + "\x1e")
                    entries.append("ffffff\x1fLATEST CHANGESET\x1fLATEST DETAIL LINE\x1e")
                    return "".join(entries)
                if args == ["diff", "--stat", "origin/main...feature/huge-pr"]:
                    return ""
                return ""

            def fake_which(name: str) -> str | None:
                if name in {"git", "gh"}:
                    return f"/usr/bin/{name}"
                return None

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                if command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"]:
                    body_file = Path(command[command.index("--body-file") + 1])
                    captured_body.append(body_file.read_text(encoding="utf-8"))
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=0,
                        stdout="https://github.com/acme/supportopia/pull/100\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected command")

            with (
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.existing_pull_request", return_value=None),
                patch("envctl_engine.actions.project_action_domain.shutil.which", side_effect=fake_which),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                code = actions_cli._run_pr_action(repo_root, repo_root, "Main")

            self.assertEqual(code, 0)
            self.assertEqual(len(captured_body), 1)
            self.assertLessEqual(len(captured_body[0]), domain.PR_BODY_MAX_CHARS)
            self.assertIn("[truncated to most recent commit messages]", captured_body[0])
            self.assertIn("LATEST CHANGESET", captured_body[0])
            self.assertIn("LATEST DETAIL LINE", captured_body[0])
            self.assertNotIn("commit 0", captured_body[0])

    def test_pr_action_prefers_explicit_pr_body_over_main_task_and_commit_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            (repo_root / "MAIN_TASK.md").write_text("Use me only as fallback\n", encoding="utf-8")
            captured_body: list[str] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/custom-body\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["merge-base", "feature/custom-body", "origin/main"]:
                    return "mbase123\n"
                if args == ["log", "-1", "--pretty=%s"]:
                    return "feat: explicit pr body\n"
                if args == [
                    "log",
                    "--reverse",
                    "--no-merges",
                    "--format=%h%x1f%s%x1f%b%x1e",
                    "mbase123..feature/custom-body",
                ]:
                    return "abc123\x1fcommit fallback\x1fbody fallback\x1e"
                return ""

            def fake_which(name: str) -> str | None:
                if name in {"git", "gh"}:
                    return f"/usr/bin/{name}"
                return None

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                if command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"]:
                    body_file = Path(command[command.index("--body-file") + 1])
                    captured_body.append(body_file.read_text(encoding="utf-8"))
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=0,
                        stdout="https://github.com/acme/supportopia/pull/111\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected command")

            with (
                patch.dict(os.environ, {"ENVCTL_PR_BODY": "Typed PR body\n\nWith details."}, clear=False),
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.existing_pull_request", return_value=None),
                patch("envctl_engine.actions.project_action_domain.shutil.which", side_effect=fake_which),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                code = actions_cli._run_pr_action(repo_root, repo_root, "Main")

            self.assertEqual(code, 0)
            self.assertEqual(len(captured_body), 1)
            self.assertEqual(captured_body[0], "Typed PR body\n\nWith details.")
            self.assertNotIn("Use me only as fallback", captured_body[0])
            self.assertNotIn("commit fallback", captured_body[0])

    def test_pr_action_interactive_mode_does_not_prompt_for_base_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            calls: list[list[str]] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/no-prompt\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["merge-base", "feature/no-prompt", "origin/main"]:
                    return "mbase123\n"
                if args == ["log", "-1", "--pretty=%s"]:
                    return "feat: promptless pr\n"
                if args == [
                    "log",
                    "--reverse",
                    "--no-merges",
                    "--format=%h%x1f%s%x1f%b%x1e",
                    "mbase123..feature/no-prompt",
                ]:
                    return "abc123\x1ffeat: demo\x1f\x1e"
                if args == ["status", "--porcelain"]:
                    return ""
                if args == ["diff", "--stat", "origin/main...feature/no-prompt"]:
                    return ""
                return ""

            def fake_which(name: str) -> str | None:
                if name in {"git", "gh"}:
                    return f"/usr/bin/{name}"
                return None

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                calls.append(command)
                if command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"]:
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=0,
                        stdout="https://github.com/acme/supportopia/pull/101\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected command")

            with (
                patch.dict(os.environ, {"ENVCTL_ACTION_INTERACTIVE": "1"}, clear=False),
                patch("sys.stdin.isatty", return_value=True),
                patch("builtins.input", side_effect=AssertionError("input() should not be called for pr action")),
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.existing_pull_request", return_value=None),
                patch("envctl_engine.actions.project_action_domain.shutil.which", side_effect=fake_which),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_pr_action(repo_root, repo_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("https://github.com/acme/supportopia/pull/101", output)
            gh_create = next(
                command for command in calls if command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"]
            )
            self.assertNotIn("--fill", gh_create)
            self.assertIn("--head", gh_create)
            self.assertIn("feature/no-prompt", gh_create)

    def test_pr_action_prefers_main_task_for_body_when_present(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            (repo_root / "MAIN_TASK.md").write_text("# Main Task\n\nShip the feature.\n", encoding="utf-8")
            captured_body: list[str] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/main-task\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["log", "-1", "--pretty=%s"]:
                    return "feat: use main task body\n"
                if args == ["diff", "--stat", "origin/main...feature/main-task"]:
                    return ""
                return ""

            def fake_which(name: str) -> str | None:
                if name in {"git", "gh"}:
                    return f"/usr/bin/{name}"
                return None

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                if command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"]:
                    body_file = Path(command[command.index("--body-file") + 1])
                    captured_body.append(body_file.read_text(encoding="utf-8"))
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=0,
                        stdout="https://github.com/acme/supportopia/pull/102\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected command")

            with (
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.existing_pull_request", return_value=None),
                patch("envctl_engine.actions.project_action_domain.shutil.which", side_effect=fake_which),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                code = actions_cli._run_pr_action(repo_root, repo_root, "Main")

            self.assertEqual(code, 0)
            self.assertEqual(len(captured_body), 1)
            self.assertEqual(captured_body[0], "# Main Task\n\nShip the feature.")
            self.assertLessEqual(len(captured_body[0]), domain.PR_BODY_MAX_CHARS)

    def test_pr_action_truncates_main_task_body_to_github_limit(self) -> None:
        domain = importlib.import_module("envctl_engine.actions.project_action_domain")
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            (repo_root / "MAIN_TASK.md").write_text(("line\n" * 20000) + "final line\n", encoding="utf-8")
            captured_body: list[str] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/main-task-limit\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["log", "-1", "--pretty=%s"]:
                    return "feat: truncate main task body\n"
                return ""

            def fake_which(name: str) -> str | None:
                if name in {"git", "gh"}:
                    return f"/usr/bin/{name}"
                return None

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                if command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"]:
                    body_file = Path(command[command.index("--body-file") + 1])
                    captured_body.append(body_file.read_text(encoding="utf-8"))
                    return subprocess.CompletedProcess(
                        args=command,
                        returncode=0,
                        stdout="https://github.com/acme/supportopia/pull/103\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected command")

            with (
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.existing_pull_request", return_value=None),
                patch("envctl_engine.actions.project_action_domain.shutil.which", side_effect=fake_which),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                code = actions_cli._run_pr_action(repo_root, repo_root, "Main")

            self.assertEqual(code, 0)
            self.assertEqual(len(captured_body), 1)
            self.assertLessEqual(len(captured_body[0]), domain.PR_BODY_MAX_CHARS)
            self.assertTrue(captured_body[0].endswith("[truncated]"))

    def test_pr_action_prefers_repo_helper_over_gh(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            helper = repo_root / "utils" / "create-pr.sh"
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.write_text("#!/bin/sh\n", encoding="utf-8")
            helper.chmod(0o755)
            calls: list[list[str]] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/helper-demo\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["merge-base", "feature/helper-demo", "origin/main"]:
                    return "mbase123\n"
                if args == ["log", "-1", "--pretty=%s"]:
                    return "feat: helper demo\n"
                if args == [
                    "log",
                    "--reverse",
                    "--no-merges",
                    "--format=%h%x1f%s%x1f%b%x1e",
                    "mbase123..feature/helper-demo",
                ]:
                    return "abc123\x1ffeat: helper demo\x1f\x1e"
                if args == ["status", "--porcelain"]:
                    return ""
                return ""

            def fake_which(name: str) -> str | None:
                if name in {"git", "gh"}:
                    return f"/usr/bin/{name}"
                return None

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                calls.append(command)
                if command[0] == str(helper.resolve()):
                    return subprocess.CompletedProcess(args=command, returncode=0, stdout="helper ok\n", stderr="")
                return subprocess.CompletedProcess(args=command, returncode=1, stdout="", stderr="unexpected command")

            with (
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.existing_pull_request", return_value=None),
                patch("envctl_engine.actions.project_action_domain.shutil.which", side_effect=fake_which),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_pr_action(repo_root, repo_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("helper ok", output)
            self.assertTrue(calls)
            self.assertEqual(calls[0][0], str(helper.resolve()))
            self.assertFalse(
                any(command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"] for command in calls), msg=calls
            )

    def test_pr_action_skips_detached_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "HEAD\n"
                return ""

            with (
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain.subprocess.run") as run_mock,
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_pr_action(repo_root, repo_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Skipping Main (detached HEAD).", output)
            run_mock.assert_not_called()
