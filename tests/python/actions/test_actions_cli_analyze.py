# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.actions.actions_cli_test_support import *  # noqa: F403,F405


class ActionsCliAnalyzeTests(unittest.TestCase):
    def test_analyze_action_branch_relative_review_uses_explicit_base_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            runtime_root = (Path(tmpdir) / "runtime" / "scope" / "tree-diffs").resolve()
            project_root = repo_root / "trees" / "feature-a" / "1"
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / ".git").write_text("gitdir: /tmp/feature-a-1\n", encoding="utf-8")
            calls: list[list[str]] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                calls.append(list(args))
                if args == ["rev-parse", "--verify", "origin/dev"]:
                    return "deadbeef\n"
                if args == ["merge-base", "HEAD", "origin/dev"]:
                    return "mbase123\n"
                if args == ["diff", "--find-renames", "--stat", "mbase123"]:
                    return " app.py | 2 +-\n"
                if args == ["diff", "--find-renames", "--name-status", "mbase123"]:
                    return "M\tapp.py\n"
                if args == ["diff", "--find-renames", "mbase123"]:
                    return "diff --git a/app.py b/app.py\n+change\n"
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return " M app.py\n?? new.txt\n"
                return ""

            with (
                patch.dict(
                    os.environ,
                    {
                        "ENVCTL_ACTION_TREE_DIFFS_ROOT": str(runtime_root),
                        "ENVCTL_ACTION_RUNTIME_ROOT": str(Path(tmpdir) / "runtime" / "scope"),
                        "ENVCTL_REVIEW_BASE": "dev",
                    },
                    clear=False,
                ),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_analyze_action(project_root, repo_root, "feature-a-1")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Review Ready: feature-a-1", output)
            written_paths = sorted((runtime_root / "review").glob("*.md"))
            self.assertEqual(len(written_paths), 1)
            markdown = written_paths[0].read_text(encoding="utf-8")
            self.assertIn("## Base branch", markdown)
            self.assertIn("dev", markdown)
            self.assertIn("## Base resolution source", markdown)
            self.assertIn("explicit", markdown)
            self.assertIn("## Merge base", markdown)
            self.assertIn("mbase123", markdown)
            self.assertIn("## Changed files", markdown)
            self.assertIn("M\tapp.py", markdown)
            self.assertIn("## Full diff", markdown)
            self.assertIn("diff --git a/app.py b/app.py", markdown)
            self.assertIn("## Working tree / untracked files", markdown)
            self.assertIn("?? new.txt", markdown)
            self.assertIn(["diff", "--find-renames", "--stat", "mbase123"], calls)

    def test_analyze_action_uses_worktree_provenance_for_review_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            runtime_root = (Path(tmpdir) / "runtime" / "scope" / "tree-diffs").resolve()
            project_root = repo_root / "trees" / "feature-a" / "1"
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / ".git").write_text("gitdir: /tmp/feature-a-1\n", encoding="utf-8")
            provenance_path = project_root / ".envctl-state" / "worktree-provenance.json"
            provenance_path.parent.mkdir(parents=True, exist_ok=True)
            provenance_path.write_text(
                (
                    "{\n"
                    '  "schema_version": 1,\n'
                    '  "plan_file": "implementations/feature-a.md",\n'
                    '  "source_branch": "release/2026.03",\n'
                    '  "source_ref": "origin/release/2026.03",\n'
                    '  "resolution_reason": "attached_branch"\n'
                    "}\n"
                ),
                encoding="utf-8",
            )
            plan_path = repo_root / "todo" / "plans" / "implementations" / "feature-a.md"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# Original plan\n\nShip feature A.\n", encoding="utf-8")

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--verify", "origin/release/2026.03"]:
                    return "deadbeef\n"
                if args == ["merge-base", "HEAD", "origin/release/2026.03"]:
                    return "mbase-provenance\n"
                if args == ["diff", "--find-renames", "--stat", "mbase-provenance"]:
                    return " api.py | 4 ++--\n"
                if args == ["diff", "--find-renames", "--name-status", "mbase-provenance"]:
                    return "M\tapi.py\n"
                if args == ["diff", "--find-renames", "mbase-provenance"]:
                    return "diff --git a/api.py b/api.py\n"
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return ""
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
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", side_effect=AssertionError("unexpected")),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
            ):
                code = actions_cli._run_analyze_action(project_root, repo_root, "feature-a-1")

            self.assertEqual(code, 0)
            written_path = next((runtime_root / "review").glob("*.md"))
            markdown = written_path.read_text(encoding="utf-8")
            self.assertIn("## Original plan file", markdown)
            self.assertIn(str(plan_path.resolve()), markdown)
            self.assertIn("## Original plan", markdown)
            self.assertIn("Ship feature A.", markdown)
            self.assertIn("release/2026.03", markdown)
            self.assertIn("provenance", markdown)
            self.assertIn("mbase-provenance", markdown)

    def test_analyze_action_falls_back_to_upstream_branch_for_review_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            runtime_root = (Path(tmpdir) / "runtime" / "scope" / "tree-diffs").resolve()
            project_root = repo_root / "trees" / "feature-a" / "1"
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / ".git").write_text("gitdir: /tmp/feature-a-1\n", encoding="utf-8")

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "feature/demo\n"
                if args == ["rev-parse", "--abbrev-ref", "feature/demo@{upstream}"]:
                    return "origin/dev\n"
                if args == ["rev-parse", "--verify", "origin/dev"]:
                    return "deadbeef\n"
                if args == ["merge-base", "HEAD", "origin/dev"]:
                    return "mbase-upstream\n"
                if args == ["diff", "--find-renames", "--stat", "mbase-upstream"]:
                    return ""
                if args == ["diff", "--find-renames", "--name-status", "mbase-upstream"]:
                    return ""
                if args == ["diff", "--find-renames", "mbase-upstream"]:
                    return ""
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return ""
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
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", side_effect=AssertionError("unexpected")),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
            ):
                code = actions_cli._run_analyze_action(project_root, repo_root, "feature-a-1")

            self.assertEqual(code, 0)
            written_path = next((runtime_root / "review").glob("*.md"))
            markdown = written_path.read_text(encoding="utf-8")
            self.assertIn("## Base branch", markdown)
            self.assertIn("dev", markdown)
            self.assertIn("upstream", markdown)

    def test_analyze_action_falls_back_to_default_branch_for_main_repo_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            runtime_root = (Path(tmpdir) / "runtime" / "scope" / "tree-diffs").resolve()
            repo_root.mkdir(parents=True, exist_ok=True)
            (repo_root / ".git").mkdir(parents=True, exist_ok=True)

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "HEAD\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["merge-base", "HEAD", "origin/main"]:
                    return "mbase-main\n"
                if args == ["diff", "--find-renames", "--stat", "mbase-main"]:
                    return ""
                if args == ["diff", "--find-renames", "--name-status", "mbase-main"]:
                    return ""
                if args == ["diff", "--find-renames", "mbase-main"]:
                    return ""
                if args == ["status", "--porcelain", "--untracked-files=all"]:
                    return ""
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
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
            ):
                code = actions_cli._run_analyze_action(repo_root, repo_root, "Main")

            self.assertEqual(code, 0)
            written_path = next((runtime_root / "review").glob("*.md"))
            markdown = written_path.read_text(encoding="utf-8")
            self.assertIn("main", markdown)
            self.assertIn("default_branch", markdown)

    def test_analyze_action_reports_invalid_explicit_review_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            runtime_root = (Path(tmpdir) / "runtime" / "scope" / "tree-diffs").resolve()
            project_root = repo_root / "trees" / "feature-a" / "1"
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / ".git").write_text("gitdir: /tmp/feature-a-1\n", encoding="utf-8")

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args in (
                    ["rev-parse", "--verify", "origin/missing-base"],
                    ["rev-parse", "--verify", "missing-base"],
                ):
                    return ""
                return ""

            with (
                patch.dict(
                    os.environ,
                    {
                        "ENVCTL_ACTION_TREE_DIFFS_ROOT": str(runtime_root),
                        "ENVCTL_ACTION_RUNTIME_ROOT": str(Path(tmpdir) / "runtime" / "scope"),
                        "ENVCTL_REVIEW_BASE": "missing-base",
                    },
                    clear=False,
                ),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
            ):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = actions_cli._run_analyze_action(project_root, repo_root, "feature-a-1")
            output = buffer.getvalue()

            self.assertEqual(code, 1)
            self.assertIn("missing-base", output)
            self.assertIn("--review-base", output)
            self.assertFalse((runtime_root / "review").exists())

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

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "HEAD\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["merge-base", "HEAD", "origin/main"]:
                    return "mbase123\n"
                return ""

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
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
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

    def test_analyze_action_helper_receives_original_plan_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            runtime_root = (Path(tmpdir) / "runtime" / "scope" / "runs" / "run-123" / "tree-diffs").resolve()
            project_root = repo_root / "trees" / "implementations_task" / "1"
            helper = repo_root / "utils" / "analyze-tree-changes.sh"
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.write_text("#!/bin/sh\n", encoding="utf-8")
            helper.chmod(0o755)
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / ".git").write_text("gitdir: /tmp/feature-a-1\n", encoding="utf-8")
            provenance_path = project_root / ".envctl-state" / "worktree-provenance.json"
            provenance_path.parent.mkdir(parents=True, exist_ok=True)
            provenance_path.write_text(
                '{\n  "schema_version": 1,\n  "plan_file": "implementations/task.md"\n}\n',
                encoding="utf-8",
            )
            plan_path = repo_root / "todo" / "plans" / "implementations" / "task.md"
            plan_path.parent.mkdir(parents=True, exist_ok=True)
            plan_path.write_text("# task\n", encoding="utf-8")
            seen_env: dict[str, str] = {}

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "HEAD\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["merge-base", "HEAD", "origin/main"]:
                    return "mbase123\n"
                return ""

            def fake_run(args: list[str], **kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                env = kwargs.get("env") or {}
                seen_env.update({str(key): str(value) for key, value in env.items()})
                output_dir_arg = next(arg for arg in command if arg.startswith("output-dir="))
                output_dir = Path(output_dir_arg.split("=", 1)[1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "summary.md").write_text("# Summary\n", encoding="utf-8")
                (output_dir / "all.md").write_text("# Full\n", encoding="utf-8")
                return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

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
                patch("envctl_engine.actions.project_action_domain.detect_default_branch", return_value="main"),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                code = actions_cli._run_analyze_action(project_root, repo_root, "implementations_task-1")

            self.assertEqual(code, 0)
            self.assertEqual(seen_env.get("ENVCTL_REVIEW_ORIGINAL_PLAN_FILE"), str(plan_path.resolve()))
            written_dir = next(runtime_root.glob("analysis_implementations_task-1_*"))
            bundle = (written_dir / "all.md").read_text(encoding="utf-8")
            self.assertIn("## Original plan file", bundle)
            self.assertIn(str(plan_path.resolve()), bundle)

    def test_analyze_action_helper_receives_explicit_review_base(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_root = Path(tmpdir) / "repo"
            runtime_root = (Path(tmpdir) / "runtime" / "scope" / "runs" / "run-123" / "tree-diffs").resolve()
            project_root = repo_root / "trees" / "feature-a" / "1"
            helper = repo_root / "utils" / "analyze-tree-changes.sh"
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.write_text("#!/bin/sh\n", encoding="utf-8")
            helper.chmod(0o755)
            project_root.mkdir(parents=True, exist_ok=True)
            (project_root / ".git").write_text("gitdir: /tmp/feature-a-1\n", encoding="utf-8")
            calls: list[list[str]] = []

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--verify", "origin/dev"]:
                    return "deadbeef\n"
                if args == ["merge-base", "HEAD", "origin/dev"]:
                    return "mbase123\n"
                return ""

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                calls.append(command)
                output_dir_arg = next(arg for arg in command if arg.startswith("output-dir="))
                output_dir = Path(output_dir_arg.split("=", 1)[1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "summary.md").write_text("# Summary\n", encoding="utf-8")
                (output_dir / "all.md").write_text("# Full\n", encoding="utf-8")
                return subprocess.CompletedProcess(args=command, returncode=0, stdout="", stderr="")

            with (
                patch.dict(
                    os.environ,
                    {
                        "ENVCTL_ACTION_TREE_DIFFS_ROOT": str(runtime_root),
                        "ENVCTL_ACTION_RUNTIME_ROOT": str(Path(tmpdir) / "runtime" / "scope"),
                        "ENVCTL_ACTION_RUN_ID": "run-123",
                        "ENVCTL_REVIEW_BASE": "dev",
                    },
                    clear=False,
                ),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                code = actions_cli._run_analyze_action(project_root, repo_root, "feature-a-1")

            self.assertEqual(code, 0)
            self.assertTrue(calls)
            self.assertIn("base-branch=dev", calls[0])
            self.assertIn("base-source=explicit", calls[0])

    def test_analyze_action_interactive_mode_does_not_prompt_for_analysis_mode(self) -> None:
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

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "HEAD\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["merge-base", "HEAD", "origin/main"]:
                    return "mbase123\n"
                return ""

            def fake_run(args: list[str], **_kwargs):  # noqa: ANN001
                command = [str(token) for token in args]
                calls.append(command)
                output_dir_arg = next(arg for arg in command if arg.startswith("output-dir="))
                output_dir = Path(output_dir_arg.split("=", 1)[1])
                output_dir.mkdir(parents=True, exist_ok=True)
                (output_dir / "summary.md").write_text("# Summary\n", encoding="utf-8")
                (output_dir / "all.md").write_text("# Full\n", encoding="utf-8")
                (output_dir / "summary_short.txt").write_text(
                    "Tree Changes Analysis Summary\n============================\nTrees analyzed: 1\n",
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
                        "ENVCTL_ACTION_INTERACTIVE": "1",
                    },
                    clear=False,
                ),
                patch("sys.stdin.isatty", return_value=True),
                patch("builtins.input", side_effect=AssertionError("input() should not be called for review action")),
                patch("envctl_engine.actions.project_action_domain.shutil.which", return_value="/usr/bin/git"),
                patch("envctl_engine.actions.project_action_domain._git_output", side_effect=fake_git_output),
                patch("envctl_engine.actions.project_action_domain.subprocess.run", side_effect=fake_run),
            ):
                code = actions_cli._run_analyze_action(project_root, repo_root, "feature-a-1")

            self.assertEqual(code, 0)
            self.assertTrue(calls)
            self.assertIn("trees=1", calls[0])

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
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "HEAD\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["merge-base", "HEAD", "origin/main"]:
                    return "mbase123\n"
                if args == ["diff", "--find-renames", "--stat", "mbase123"]:
                    return " app.py | 2 +-\n"
                if args == ["diff", "--find-renames", "--name-status", "mbase123"]:
                    return "M\tapp.py\n"
                if args == ["diff", "--find-renames", "mbase123"]:
                    return "diff --git a/app.py b/app.py\n"
                if args == ["status", "--porcelain", "--untracked-files=all"]:
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
            written_path = next(Path(line.strip()) for line in output.splitlines() if line.strip().endswith(".md"))
            self.assertTrue(written_path.is_file())
            self.assertTrue(written_path.resolve().is_relative_to(runtime_root))
            self.assertFalse((repo_root / "review").exists())
            self.assertFalse((repo_root / "tree-diffs").exists())
            run_mock.assert_not_called()

    def test_analyze_action_for_main_repo_does_not_treat_parent_directory_as_tree_family(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            parent = Path(tmpdir) / "projects"
            repo_root = parent / "supportopia"
            sibling_repo = parent / "envctl"
            runtime_root = (Path(tmpdir) / "runtime" / "scope" / "tree-diffs").resolve()
            helper = repo_root / "utils" / "analyze-tree-changes.sh"
            helper.parent.mkdir(parents=True, exist_ok=True)
            helper.write_text("#!/bin/sh\n", encoding="utf-8")
            helper.chmod(0o755)
            repo_root.mkdir(parents=True, exist_ok=True)
            sibling_repo.mkdir(parents=True, exist_ok=True)
            (repo_root / ".git").write_text("gitdir: /tmp/supportopia\n", encoding="utf-8")
            (sibling_repo / ".git").write_text("gitdir: /tmp/envctl\n", encoding="utf-8")

            def fake_git_output(_git_root: Path, args: list[str]) -> str:
                if args == ["rev-parse", "--abbrev-ref", "HEAD"]:
                    return "HEAD\n"
                if args == ["rev-parse", "--verify", "origin/main"]:
                    return "deadbeef\n"
                if args == ["merge-base", "HEAD", "origin/main"]:
                    return "mbase-main\n"
                if args == ["diff", "--find-renames", "--stat", "mbase-main"]:
                    return " app.py | 2 +-\n"
                if args == ["diff", "--find-renames", "--name-status", "mbase-main"]:
                    return "M\tapp.py\n"
                if args == ["diff", "--find-renames", "mbase-main"]:
                    return "diff --git a/app.py b/app.py\n"
                if args == ["status", "--porcelain", "--untracked-files=all"]:
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
                    code = actions_cli._run_analyze_action(repo_root, repo_root, "Main")
            output = buffer.getvalue()

            self.assertEqual(code, 0)
            self.assertIn("Review Ready: Main", output)
            self.assertIn("Summary file", output)
            self.assertNotIn("No /", output)
            self.assertFalse((repo_root / "review").exists())
            self.assertFalse((repo_root / "tree-diffs").exists())
            run_mock.assert_not_called()
