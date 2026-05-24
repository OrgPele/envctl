# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.actions.actions_cli_test_support import *  # noqa: F403,F405


class ActionsCliCommitTests(unittest.TestCase):
    def test_commit_action_uses_main_task_and_pushes_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            ledger = project_root / ".envctl-commit-message.md"
            ledger.write_text(
                "# Envctl Commit Log\n\n### Envctl pointer ###\nShip the feature\n",
                encoding="utf-8",
            )
            seen_git_args: list[list[str]] = []

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout=" M app.py\n", stderr="")
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M  app.py\n", stderr="")
                if args[:2] == ["commit", "-F"]:
                    return subprocess.CompletedProcess(
                        args=args, returncode=0, stdout="[feature/demo abc123] Ship it\n", stderr=""
                    )
                if args[:3] == ["push", "-u", "origin"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Committed and pushed changes for Main (feature/demo).", output)
            commit_args = next(args for args in seen_git_args if args[:2] == ["commit", "-F"])
            self.assertTrue(commit_args[2].endswith(".envctl-commit-message.txt"))
            self.assertIn(["push", "-u", "origin", "feature/demo"], seen_git_args)
            self.assertEqual(ledger.read_text(encoding="utf-8"), "# Envctl Commit Log\n\nShip the feature\n\n### Envctl pointer ###\n")

    def test_commit_action_respects_pr_remote_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-commit-message.md").write_text(
                "# Envctl Commit Log\n\n### Envctl pointer ###\nShip the feature\n",
                encoding="utf-8",
            )
            seen_git_args: list[list[str]] = []

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout=" M app.py\n", stderr="")
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M  app.py\n", stderr="")
                if args[:2] == ["commit", "-F"]:
                    return subprocess.CompletedProcess(
                        args=args, returncode=0, stdout="[feature/demo abc123] Ship it\n", stderr=""
                    )
                if args[:3] == ["push", "-u", "fork"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch.dict(os.environ, {"PR_REMOTE": "fork"}, clear=False),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                code = actions_cli._run_commit_action(project_root, "Main")

            self.assertEqual(code, 0)
            self.assertIn(["push", "-u", "fork", "feature/demo"], seen_git_args)

    def test_commit_action_uses_envctl_pointer_segment_and_advances_pointer_after_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            ledger = project_root / ".envctl-commit-message.md"
            ledger.write_text(
                "# Envctl Commit Log\n\n"
                "Historical summary that should stay archived.\n\n"
                "### Envctl pointer ###\n"
                "Ship the feature\n\n"
                "- bullet one\n"
                "- bullet two\n",
                encoding="utf-8",
            )
            seen_git_args: list[list[str]] = []
            captured_commit_message: list[str] = []

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout=" M app.py\n", stderr="")
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M  app.py\n", stderr="")
                if args[:2] == ["commit", "-F"]:
                    captured_commit_message.append(Path(args[2]).read_text(encoding="utf-8"))
                    return subprocess.CompletedProcess(
                        args=args, returncode=0, stdout="[feature/demo abc123] Ship it\n", stderr=""
                    )
                if args[:3] == ["push", "-u", "origin"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                code = actions_cli._run_commit_action(project_root, "Main")

            self.assertEqual(code, 0)
            self.assertEqual(len(captured_commit_message), 1)
            self.assertEqual(captured_commit_message[0], "Ship the feature\n\n- bullet one\n- bullet two")
            self.assertTrue(any(args[:2] == ["commit", "-F"] for args in seen_git_args))
            self.assertEqual(
                ledger.read_text(encoding="utf-8"),
                "# Envctl Commit Log\n\n"
                "Historical summary that should stay archived.\n\n"
                "Ship the feature\n\n"
                "- bullet one\n"
                "- bullet two\n\n"
                "### Envctl pointer ###\n",
            )

    def test_commit_action_bootstraps_missing_envctl_commit_ledger_and_fails_when_segment_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            ledger = project_root / ".envctl-commit-message.md"
            seen_git_args: list[list[str]] = []

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout=" M app.py\n", stderr="")
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M  app.py\n", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 1)
            self.assertIn("Envctl commit log is empty after the pointer", output)
            self.assertFalse(any(args[:2] == ["commit", "-F"] for args in seen_git_args))
            self.assertEqual(ledger.read_text(encoding="utf-8"), "# Envctl Commit Log\n\n### Envctl pointer ###\n")

    def test_commit_action_renders_clickable_missing_commit_message_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            missing_file = project_root / "missing-message.txt"

            def fake_run_git(_git_root: Path, args: list[str]):
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout=" M app.py\n", stderr="")
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M  app.py\n", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch.dict(
                    os.environ,
                    {"ENVCTL_COMMIT_MESSAGE_FILE": str(missing_file), "ENVCTL_UI_HYPERLINK_MODE": "on"},
                    clear=False,
                ),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                buffer = _TtyStringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")
                output = buffer.getvalue()

            self.assertEqual(code, 1)
            self.assertIn("\x1b]8;;file://", output)
            self.assertIn(f"Commit message file is missing or empty: {missing_file}", strip_ansi(output))

    def test_commit_action_renders_clickable_ledger_path_in_empty_pointer_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            ledger = project_root / ".envctl-commit-message.md"

            def fake_run_git(_git_root: Path, args: list[str]):
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout=" M app.py\n", stderr="")
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M  app.py\n", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch.dict(os.environ, {"ENVCTL_UI_HYPERLINK_MODE": "on"}, clear=False),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                buffer = _TtyStringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")
                output = buffer.getvalue()

            self.assertEqual(code, 1)
            self.assertIn("\x1b]8;;file://", output)
            visible = strip_ansi(output)
            self.assertIn("Envctl commit log is empty after the pointer", visible)
            self.assertIn(str(ledger), visible)

    def test_commit_action_explicit_message_overrides_envctl_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            ledger = project_root / ".envctl-commit-message.md"
            ledger.write_text(
                "# Envctl Commit Log\n\n### Envctl pointer ###\nQueued default summary\n",
                encoding="utf-8",
            )
            seen_git_args: list[list[str]] = []

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout=" M app.py\n", stderr="")
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M  app.py\n", stderr="")
                if args[:2] == ["commit", "-m"]:
                    return subprocess.CompletedProcess(
                        args=args, returncode=0, stdout="[feature/demo abc123] explicit\n", stderr=""
                    )
                if args[:3] == ["push", "-u", "origin"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch.dict(os.environ, {"ENVCTL_COMMIT_MESSAGE": "Explicit summary"}, clear=False),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                code = actions_cli._run_commit_action(project_root, "Main")

            self.assertEqual(code, 0)
            self.assertIn(["commit", "-m", "Explicit summary"], seen_git_args)
            self.assertEqual(
                ledger.read_text(encoding="utf-8"),
                "# Envctl Commit Log\n\n### Envctl pointer ###\nQueued default summary\n",
            )

    def test_commit_action_explicit_message_file_overrides_envctl_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            ledger = project_root / ".envctl-commit-message.md"
            ledger.write_text(
                "# Envctl Commit Log\n\n### Envctl pointer ###\nQueued default summary\n",
                encoding="utf-8",
            )
            message_file = project_root / "custom-message.txt"
            message_file.write_text("Explicit file summary\n", encoding="utf-8")
            seen_git_args: list[list[str]] = []

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout=" M app.py\n", stderr="")
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M  app.py\n", stderr="")
                if args[:2] == ["commit", "-F"]:
                    return subprocess.CompletedProcess(
                        args=args, returncode=0, stdout="[feature/demo abc123] explicit file\n", stderr=""
                    )
                if args[:3] == ["push", "-u", "origin"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch.dict(os.environ, {"ENVCTL_COMMIT_MESSAGE_FILE": str(message_file)}, clear=False),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                code = actions_cli._run_commit_action(project_root, "Main")

            self.assertEqual(code, 0)
            self.assertIn(["commit", "-F", str(message_file)], seen_git_args)
            self.assertEqual(
                ledger.read_text(encoding="utf-8"),
                "# Envctl Commit Log\n\n### Envctl pointer ###\nQueued default summary\n",
            )

    def test_commit_action_uses_entire_envctl_ledger_when_marker_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            ledger = project_root / ".envctl-commit-message.md"
            ledger.write_text("Ship the feature without a marker.\n", encoding="utf-8")
            seen_git_args: list[list[str]] = []
            captured_commit_message: list[str] = []

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout=" M app.py\n", stderr="")
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M  app.py\n", stderr="")
                if args[:2] == ["commit", "-F"]:
                    captured_commit_message.append(Path(args[2]).read_text(encoding="utf-8"))
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout="[feature/demo abc123] Ship it\n",
                        stderr="",
                    )
                if args[:3] == ["push", "-u", "origin"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Committed and pushed changes for Main (feature/demo).", output)
            self.assertIn(["push", "-u", "origin", "feature/demo"], seen_git_args)
            self.assertEqual(captured_commit_message, ["Ship the feature without a marker."])
            self.assertEqual(
                ledger.read_text(encoding="utf-8"),
                "Ship the feature without a marker.\n\n### Envctl pointer ###\n",
            )

    def test_commit_action_fails_when_envctl_ledger_has_duplicate_markers(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            ledger = project_root / ".envctl-commit-message.md"
            ledger.write_text(
                "# Envctl Commit Log\n\n"
                "### Envctl pointer ###\n"
                "First queued summary\n\n"
                "### Envctl pointer ###\n"
                "Second queued summary\n",
                encoding="utf-8",
            )

            def fake_run_git(_git_root: Path, args: list[str]):
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout=" M app.py\n", stderr="")
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M  app.py\n", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 1)
            self.assertIn("contains multiple pointer markers", output)

    def test_commit_action_push_failure_keeps_pointer_advanced_after_successful_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            ledger = project_root / ".envctl-commit-message.md"
            ledger.write_text(
                "# Envctl Commit Log\n\n"
                "Already committed summary\n\n"
                "### Envctl pointer ###\n"
                "Newest queued summary\n",
                encoding="utf-8",
            )
            captured_commit_message: list[str] = []

            def fake_run_git(_git_root: Path, args: list[str]):
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout=" M app.py\n", stderr="")
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M  app.py\n", stderr="")
                if args[:2] == ["commit", "-F"]:
                    captured_commit_message.append(Path(args[2]).read_text(encoding="utf-8"))
                    return subprocess.CompletedProcess(
                        args=args, returncode=0, stdout="[feature/demo abc123] queued\n", stderr=""
                    )
                if args[:3] == ["push", "-u", "origin"]:
                    return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="push failed")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 1)
            self.assertEqual(captured_commit_message, ["Newest queued summary"])
            self.assertIn("git push failed", output)
            self.assertEqual(
                ledger.read_text(encoding="utf-8"),
                "# Envctl Commit Log\n\n"
                "Already committed summary\n\n"
                "Newest queued summary\n\n"
                "### Envctl pointer ###\n",
            )

    def test_commit_action_skips_envctl_local_artifacts_and_commits_normal_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            ledger = project_root / ".envctl-commit-message.md"
            ledger.write_text(
                "# Envctl Commit Log\n\n### Envctl pointer ###\nShip the feature\n",
                encoding="utf-8",
            )
            seen_git_args: list[list[str]] = []

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout="?? .envctl-commit-message.md\n?? MAIN_TASK.md\n M app.py\n",
                        stderr="",
                    )
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M  app.py\n", stderr="")
                if args[:2] == ["commit", "-F"]:
                    return subprocess.CompletedProcess(
                        args=args, returncode=0, stdout="[feature/demo abc123] Ship it\n", stderr=""
                    )
                if args[:3] == ["push", "-u", "origin"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Skipping envctl-local artifacts: .envctl-commit-message.md, MAIN_TASK.md", output)
            self.assertIn(["add", "--", "app.py"], seen_git_args)
            self.assertIn(["push", "-u", "origin", "feature/demo"], seen_git_args)

    def test_commit_action_noops_when_only_envctl_local_artifacts_are_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)

            def fake_run_git(_git_root: Path, args: list[str]):
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout="?? .envctl\n?? OLD_TASK_feature.md\n",
                        stderr="",
                    )
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Skipping envctl-local artifacts: .envctl, OLD_TASK_feature.md", output)
            self.assertIn("No changes to commit for feature/demo.", output)

    def test_commit_action_recovers_when_envctl_local_artifacts_are_already_staged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / ".envctl-commit-message.md").write_text(
                "# Envctl Commit Log\n\n### Envctl pointer ###\nRecover protected artifacts\n",
                encoding="utf-8",
            )
            seen_git_args: list[list[str]] = []
            status_with_untracked_outputs = iter(
                [
                    "A  MAIN_TASK.md\n?? .envctl-commit-message.md\n M app.py\n",
                    "?? MAIN_TASK.md\n?? .envctl-commit-message.md\n M app.py\n",
                ]
            )

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout=next(status_with_untracked_outputs),
                        stderr="",
                    )
                if args == ["reset", "-q", "--", "MAIN_TASK.md"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout="M  app.py\n?? MAIN_TASK.md\n?? .envctl-commit-message.md\n",
                        stderr="",
                    )
                if args[:2] == ["commit", "-F"]:
                    return subprocess.CompletedProcess(
                        args=args, returncode=0, stdout="[feature/demo abc123] Recover\n", stderr=""
                    )
                if args[:3] == ["push", "-u", "origin"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Unstaged envctl-local artifacts: MAIN_TASK.md", output)
            self.assertIn("Skipping envctl-local artifacts: MAIN_TASK.md, .envctl-commit-message.md", output)
            self.assertNotIn("Refusing to commit", output)
            self.assertIn(["reset", "-q", "--", "MAIN_TASK.md"], seen_git_args)
            self.assertIn(["add", "--", "app.py"], seen_git_args)
            self.assertIn(["push", "-u", "origin", "feature/demo"], seen_git_args)

    def test_commit_action_unstages_staged_envctl_ledger_but_still_uses_it_for_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            ledger = project_root / ".envctl-commit-message.md"
            ledger.write_text(
                "# Envctl Commit Log\n\n### Envctl pointer ###\nLedger supplied summary\n",
                encoding="utf-8",
            )
            seen_git_args: list[list[str]] = []
            captured_commit_message: list[str] = []
            status_with_untracked_outputs = iter(
                [
                    "A  .envctl-commit-message.md\n M app.py\n",
                    "?? .envctl-commit-message.md\n M app.py\n",
                ]
            )

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout=next(status_with_untracked_outputs),
                        stderr="",
                    )
                if args == ["reset", "-q", "--", ".envctl-commit-message.md"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["add", "--", "app.py"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout="M  app.py\n?? .envctl-commit-message.md\n",
                        stderr="",
                    )
                if args[:2] == ["commit", "-F"]:
                    captured_commit_message.append(Path(args[2]).read_text(encoding="utf-8"))
                    return subprocess.CompletedProcess(
                        args=args, returncode=0, stdout="[feature/demo abc123] Ledger\n", stderr=""
                    )
                if args[:3] == ["push", "-u", "origin"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Unstaged envctl-local artifacts: .envctl-commit-message.md", output)
            self.assertEqual(captured_commit_message, ["Ledger supplied summary"])
            self.assertIn(["reset", "-q", "--", ".envctl-commit-message.md"], seen_git_args)
            self.assertEqual(
                ledger.read_text(encoding="utf-8"),
                "# Envctl Commit Log\n\nLedger supplied summary\n\n### Envctl pointer ###\n",
            )

    def test_commit_action_noops_when_only_staged_envctl_local_artifacts_remain_after_unstage(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            seen_git_args: list[list[str]] = []
            status_with_untracked_outputs = iter(
                [
                    "A  MAIN_TASK.md\nA  .envctl-state/worktree-provenance.json\n",
                    "?? MAIN_TASK.md\n?? .envctl-state/worktree-provenance.json\n",
                ]
            )

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout=next(status_with_untracked_outputs),
                        stderr="",
                    )
                if args == ["reset", "-q", "--", "MAIN_TASK.md", ".envctl-state/worktree-provenance.json"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout="?? MAIN_TASK.md\n?? .envctl-state/worktree-provenance.json\n",
                        stderr="",
                    )
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn(
                "Unstaged envctl-local artifacts: MAIN_TASK.md, .envctl-state/worktree-provenance.json",
                output,
            )
            self.assertIn(
                "Skipping envctl-local artifacts: MAIN_TASK.md, .envctl-state/worktree-provenance.json",
                output,
            )
            self.assertIn("No changes to commit for feature/demo.", output)
            self.assertFalse(any(args and args[0] == "add" for args in seen_git_args), msg=seen_git_args)
            self.assertFalse(any(args and args[0] == "commit" for args in seen_git_args), msg=seen_git_args)
            self.assertFalse(any(args and args[0] == "push" for args in seen_git_args), msg=seen_git_args)

    def test_commit_action_fails_when_unstaging_envctl_local_artifacts_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            seen_git_args: list[list[str]] = []

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=0,
                        stdout="A  MAIN_TASK.md\n?? .envctl-commit-message.md\n M app.py\n",
                        stderr="",
                    )
                if args == ["reset", "-q", "--", "MAIN_TASK.md"]:
                    return subprocess.CompletedProcess(
                        args=args,
                        returncode=128,
                        stdout="",
                        stderr="fatal: reset failed\n",
                    )
                return subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")

            with (
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._run_git", side_effect=fake_run_git),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 1)
            self.assertIn("git reset protected envctl-local artifacts failed", output)
            self.assertIn("Protected envctl-local artifacts still staged: MAIN_TASK.md", output)
            self.assertNotIn(
                "Protected envctl-local artifacts still staged: MAIN_TASK.md, .envctl-commit-message.md",
                output,
            )
            self.assertFalse(any(args and args[0] == "add" for args in seen_git_args), msg=seen_git_args)
            self.assertFalse(any(args and args[0] == "commit" for args in seen_git_args), msg=seen_git_args)
            self.assertFalse(any(args and args[0] == "push" for args in seen_git_args), msg=seen_git_args)

    def test_commit_action_interactive_mode_does_not_prompt_for_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)

            with (
                patch.dict(os.environ, {"ENVCTL_ACTION_INTERACTIVE": "1"}, clear=False),
                patch("sys.stdin.isatty", return_value=True),
                patch("builtins.input", side_effect=AssertionError("input() should not be called for commit action")),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch(
                    "envctl_engine.actions.project_action_domain._run_git",
                    side_effect=lambda _git_root, args: (
                        subprocess.CompletedProcess(
                            args=args,
                            returncode=0,
                            stdout="feature/demo\n" if args == ["rev-parse", "--abbrev-ref", "HEAD"] else "",
                            stderr="",
                        )
                        if args == ["rev-parse", "--abbrev-ref", "HEAD"]
                        else subprocess.CompletedProcess(
                            args=args,
                            returncode=0,
                            stdout=" M app.py\n",
                            stderr="",
                        )
                        if args == ["status", "--porcelain", "--untracked-files=all"]
                        else subprocess.CompletedProcess(
                            args=args,
                            returncode=0,
                            stdout="",
                            stderr="",
                        )
                        if args == ["add", "--", "app.py"]
                        else subprocess.CompletedProcess(
                            args=args,
                            returncode=0,
                            stdout="M  app.py\n",
                            stderr="",
                        )
                        if args == ["status", "--porcelain"]
                        else subprocess.CompletedProcess(args=args, returncode=1, stdout="", stderr="unexpected")
                    ),
                ),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_commit_action(project_root, "Main")

            self.assertEqual(code, 1)
            self.assertIn("Envctl commit log is empty after the pointer", buffer.getvalue())

    def test_headless_main_commit_recovers_staged_envctl_artifacts_with_real_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_root = Path(tmpdir)
            repo_root = tmp_root / "repo"
            origin = tmp_root / "origin.git"
            home = tmp_root / "home"
            home.mkdir(parents=True, exist_ok=True)
            git_env = {
                **{
                    key: value
                    for key, value in os.environ.items()
                    if key != "ENVCTL_EXECUTION_ROOT"
                },
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / ".config"),
                "GIT_CONFIG_GLOBAL": str(home / ".gitconfig"),
                "GIT_TERMINAL_PROMPT": "0",
            }

            def git(args: list[str], *, cwd: Path = repo_root) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    ["git", *args],
                    cwd=str(cwd),
                    env=git_env,
                    text=True,
                    capture_output=True,
                    check=True,
                )

            subprocess.run(
                ["git", "init", "--bare", str(origin)],
                env=git_env,
                text=True,
                capture_output=True,
                check=True,
            )
            repo_root.mkdir(parents=True, exist_ok=True)
            git(["init"])
            git(["config", "user.email", "envctl-tests@example.invalid"])
            git(["config", "user.name", "Envctl Tests"])
            git(["checkout", "-b", "feature/protected-recovery"])
            (repo_root / "app.py").write_text("print('initial')\n", encoding="utf-8")
            git(["add", "app.py"])
            git(["commit", "-m", "initial"])
            git(["remote", "add", "origin", str(origin)])
            git(["push", "-u", "origin", "feature/protected-recovery"])
            initial_head = git(["rev-parse", "HEAD"]).stdout.strip()

            (repo_root / "app.py").write_text("print('changed')\n", encoding="utf-8")
            (repo_root / "MAIN_TASK.md").write_text("# Protected task\n", encoding="utf-8")
            ledger = repo_root / ".envctl-commit-message.md"
            ledger.write_text(
                "# Envctl Commit Log\n\n### Envctl pointer ###\nReal integration summary\n",
                encoding="utf-8",
            )
            git(["add", "."])

            env = {
                **git_env,
                "RUN_REPO_ROOT": str(repo_root),
                "ENVCTL_DEFAULT_MODE": "main",
                "ENVCTL_SPINNER": "0",
                "ENVCTL_USE_REPO_WRAPPER": "1",
                "PYTHONPATH": str(PYTHON_ROOT),
            }
            completed = subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "bin" / "envctl"),
                    "commit",
                    "--headless",
                    "--main",
                ],
                cwd=str(repo_root),
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}")
            new_head = git(["rev-parse", "HEAD"]).stdout.strip()
            pushed_head = git(["rev-parse", "origin/feature/protected-recovery"]).stdout.strip()
            committed_files = git(["ls-tree", "-r", "--name-only", "HEAD"]).stdout.splitlines()
            self.assertNotEqual(new_head, initial_head)
            self.assertEqual(pushed_head, new_head)
            self.assertEqual(git(["log", "-1", "--pretty=%B"]).stdout.strip(), "Real integration summary")
            self.assertEqual(committed_files, ["app.py"])
            self.assertEqual(git(["diff", "--cached", "--name-only"]).stdout.strip(), "")
            self.assertTrue((repo_root / "MAIN_TASK.md").is_file())
            self.assertEqual(
                ledger.read_text(encoding="utf-8"),
                "# Envctl Commit Log\n\nReal integration summary\n\n### Envctl pointer ###\n",
            )
