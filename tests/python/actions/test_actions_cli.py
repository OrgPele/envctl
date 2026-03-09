from __future__ import annotations

import importlib
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import sys
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

actions_cli = importlib.import_module("envctl_engine.actions.actions_cli")


class ActionsCliTests(unittest.TestCase):
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
                patch("envctl_engine.actions.project_action_domain.existing_pr_url", return_value="https://github.com/acme/supportopia/pull/42"),
                patch("envctl_engine.actions.project_action_domain.shutil.which", side_effect=fake_which),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_pr_action(repo_root, repo_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("PR already exists: https://github.com/acme/supportopia/pull/42", output)
            self.assertIn("PR summary written:", output)
            self.assertEqual(calls, [])

    def test_pr_action_create_path_runs_gh_by_default_when_no_existing_pr(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            repo_root.mkdir(parents=True, exist_ok=True)
            calls: list[list[str]] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/new-demo\n"
                if args and args[0:2] == ["log", "--oneline"]:
                    return "abc123 feat: demo\n"
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
                if command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"]:
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
                patch("envctl_engine.actions.project_action_domain.existing_pr_url", return_value=""),
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
            self.assertIn("PR summary written:", output)
            self.assertTrue(any(command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"] for command in calls), msg=calls)

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
                if args and args[0:2] == ["log", "--oneline"]:
                    return "abc123 feat: helper demo\n"
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
                patch("envctl_engine.actions.project_action_domain.existing_pr_url", return_value=""),
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
            self.assertFalse(any(command[0] == "/usr/bin/gh" and command[1:3] == ["pr", "create"] for command in calls), msg=calls)

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

    def test_commit_action_uses_main_task_and_pushes_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / "MAIN_TASK.md").write_text("Ship the feature\n", encoding="utf-8")
            seen_git_args: list[list[str]] = []

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["add", "-A"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M app.py\n", stderr="")
                if args[:2] == ["commit", "-F"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="[feature/demo abc123] Ship it\n", stderr="")
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
            self.assertIn(["commit", "-F", str((project_root / "MAIN_TASK.md").resolve())], seen_git_args)
            self.assertIn(["push", "-u", "origin", "feature/demo"], seen_git_args)

    def test_commit_action_respects_pr_remote_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            project_root = Path(tmpdir) / "repo"
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / "MAIN_TASK.md").write_text("Ship the feature\n", encoding="utf-8")
            seen_git_args: list[list[str]] = []

            def fake_run_git(_git_root: Path, args: list[str]):
                seen_git_args.append(list(args))
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="feature/demo\n", stderr="")
                if args == ["add", "-A"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")
                if args == ["status", "--porcelain"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="M app.py\n", stderr="")
                if args[:2] == ["commit", "-F"]:
                    return subprocess.CompletedProcess(args=args, returncode=0, stdout="[feature/demo abc123] Ship it\n", stderr="")
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

    def test_analyze_action_prefers_repo_helper_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            runtime_root = (Path(tmpdir) / "runtime" / "scope" / "runs" / "run-123" / "tree-diffs").resolve()
            project_root = repo_root / "trees" / "feature-a" / "1"
            sibling_root = repo_root / "trees" / "feature-a" / "2"
            helper = repo_root / "utils" / "analyze-tree-changes.sh"
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.write_text("#!/bin/sh\n", encoding="utf-8")
            helper.chmod(0o755)
            project_root.mkdir(parents=True, exist_ok=True)
            sibling_root.mkdir(parents=True, exist_ok=True)
            (project_root / ".git").write_text("gitdir: /tmp/feature-a-1\n", encoding="utf-8")
            (sibling_root / ".git").write_text("gitdir: /tmp/feature-a-2\n", encoding="utf-8")
            calls: list[list[str]] = []

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                calls.append(command)
                output_dir_arg = next(arg for arg in command if arg.startswith("output-dir="))
                output_dir = Path(output_dir_arg.split("=", 1)[1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "summary.md").write_text("# Summary\n", encoding="utf-8")
                (output_dir / "all.md").write_text("# Full\n", encoding="utf-8")
                (output_dir / "prompt.md").write_text("# Prompt\n", encoding="utf-8")
                (output_dir / "summary_short.txt").write_text(
                    "Tree Changes Analysis Summary\n"
                    "============================\n"
                    "Base branch: dev\n"
                    "Trees analyzed: 1\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(args=command, returncode=0, stdout="analysis ok\n", stderr="")

            with (
                patch.dict(
                    os.environ,
                    {
                        "ENVCTL_ACTION_TREE_DIFFS_ROOT": str(runtime_root),
                        "ENVCTL_ACTION_RUNTIME_ROOT": str(Path(tmpdir) / "runtime" / "scope"),
                        "ENVCTL_ACTION_RUN_ID": "run-123",
                    },
                    clear=False,
                ),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_analyze_action(project_root, repo_root, "feature-a-1")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Review Ready: feature-a-1", output)
            self.assertIn("Output directory", output)
            self.assertIn("Summary file", output)
            self.assertIn("Full review bundle", output)
            self.assertIn("Trees analyzed: 1", output)
            self.assertNotIn("analysis ok", output)
            self.assertNotIn("/private/tmp/", output)
            self.assertTrue(calls, msg="expected helper invocation")
            self.assertEqual(calls[0][0], str(helper.resolve()))
            self.assertIn("trees=1", calls[0])
            self.assertIn("approach=optimal", calls[0])
            output_dir_arg = next(arg for arg in calls[0] if arg.startswith("output-dir="))
            self.assertTrue(output_dir_arg.startswith(f"output-dir={runtime_root}/analysis_feature-a-1_"))
            written_dir = Path(output_dir_arg.split("=", 1)[1])
            self.assertTrue((written_dir / "summary.md").is_file())
            self.assertTrue((written_dir / "all.md").is_file())
            self.assertFalse((written_dir / "prompt.md").exists())
            self.assertFalse((written_dir / "summary_short.txt").exists())
            self.assertFalse((repo_root / "tree-diffs").exists())

    def test_analyze_action_falls_back_when_helper_is_not_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            runtime_root = (Path(tmpdir) / "runtime" / "scope" / "tree-diffs").resolve()
            project_root = repo_root / "trees" / "feature-a" / "1"
            helper = repo_root / "utils" / "analyze-tree-changes.sh"
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.write_text("#!/bin/sh\n", encoding="utf-8")
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / ".git").write_text("gitdir: /tmp/feature-a-1\n", encoding="utf-8")

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["diff", "--stat"]:
                    return " app.py | 2 +-\n"
                if args == ["status", "--porcelain"]:
                    return " M app.py\n"
                return ""

            with (
                patch.dict(
                    os.environ,
                    {
                        "ENVCTL_ACTION_TREE_DIFFS_ROOT": str(runtime_root),
                        "ENVCTL_ACTION_RUNTIME_ROOT": str(Path(tmpdir) / "runtime" / "scope"),
                    },
                    clear=False,
                ),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.subprocess.run") as run_mock,
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_analyze_action(project_root, repo_root, "feature-a-1")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Review Ready: feature-a-1", output)
            self.assertIn("Summary file", output)
            self.assertIn("Full review bundle", output)
            self.assertIn("Output directory", output)
            written_path = next(
                Path(line.strip())
                for line in output.splitlines()
                if line.strip().endswith(".md")
            )
            self.assertTrue(written_path.is_file())
            self.assertTrue(written_path.resolve().is_relative_to(runtime_root))
            self.assertFalse((repo_root / "review").exists())
            self.assertFalse((repo_root / "tree-diffs").exists())
            run_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
