from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[3]
PYTHON_ROOT = REPO_ROOT / "python"
from envctl_engine.runtime.command_router import parse_route
from envctl_engine.runtime.prompt_install_support import (  # noqa: E402
    _available_presets,
    _load_template,
    _print_install_results,
    _render_claude_template,
    _render_codex_template,
    _render_opencode_template,
    PromptInstallResult,
    run_install_prompts_command,
)
from envctl_engine.test_output.parser_base import strip_ansi


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class PromptInstallSupportTests(unittest.TestCase):
    def test_install_prompts_dry_run_json_reports_all_targets_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "all", "--dry-run", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["command"], "install-prompts")
            self.assertEqual(payload["preset"], "all")
            self.assertTrue(payload["dry_run"])
            expected_presets = sorted(_available_presets())
            expected_paths = [
                str(Path(tmpdir) / ".codex" / "prompts" / f"{preset}.md") for preset in expected_presets
            ] + [
                str(Path(tmpdir) / ".claude" / "commands" / f"{preset}.md") for preset in expected_presets
            ] + [
                str(Path(tmpdir) / ".config" / "opencode" / "commands" / f"{preset}.md") for preset in expected_presets
            ]
            self.assertEqual([item["path"] for item in payload["results"]], expected_paths)
            self.assertEqual(
                [item["cli"] for item in payload["results"]],
                ["codex"] * len(expected_presets)
                + ["claude"] * len(expected_presets)
                + ["opencode"] * len(expected_presets),
            )
            self.assertTrue(all(item["status"] == "planned" for item in payload["results"]))
            self.assertFalse((Path(tmpdir) / ".codex" / "prompts" / "implement_task.md").exists())
            self.assertFalse((Path(tmpdir) / ".claude" / "commands" / "implement_task.md").exists())
            self.assertFalse((Path(tmpdir) / ".config" / "opencode" / "commands" / "implement_task.md").exists())

    def test_install_prompts_omitted_preset_defaults_to_all_for_selected_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "codex", "--dry-run", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            expected_presets = sorted(_available_presets())
            self.assertEqual(payload["preset"], "all")
            self.assertEqual(
                [item["path"] for item in payload["results"]],
                [str(Path(tmpdir) / ".codex" / "prompts" / f"{preset}.md") for preset in expected_presets],
            )
            self.assertEqual(
                [item["message"] for item in payload["results"]],
                [f"Would install {preset} for codex" for preset in expected_presets],
            )

    def test_install_prompts_positional_all_installs_every_preset_for_selected_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "codex", "all", "--dry-run"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            rendered = buffer.getvalue()
            self.assertIn("Would install implement_task for codex", rendered)
            self.assertIn("Would install review_task_imp for codex", rendered)
            self.assertIn("Would install review_worktree_imp for codex", rendered)
            self.assertIn("Would install continue_task for codex", rendered)
            self.assertIn("Would install merge_trees_into_dev for codex", rendered)
            self.assertIn("Would install create_plan for codex", rendered)
            self.assertIn("Would install implement_plan for codex", rendered)
            self.assertEqual(rendered.count("codex: planned "), 7)

    def test_install_prompts_flag_all_installs_every_preset_for_selected_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "codex", "--preset", "all", "--dry-run", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["preset"], "all")
            self.assertEqual(
                [item["path"] for item in payload["results"]],
                [
                    str(Path(tmpdir) / ".codex" / "prompts" / "continue_task.md"),
                    str(Path(tmpdir) / ".codex" / "prompts" / "create_plan.md"),
                    str(Path(tmpdir) / ".codex" / "prompts" / "implement_plan.md"),
                    str(Path(tmpdir) / ".codex" / "prompts" / "implement_task.md"),
                    str(Path(tmpdir) / ".codex" / "prompts" / "merge_trees_into_dev.md"),
                    str(Path(tmpdir) / ".codex" / "prompts" / "review_task_imp.md"),
                    str(Path(tmpdir) / ".codex" / "prompts" / "review_worktree_imp.md"),
                ],
            )

    def test_install_prompts_prompts_once_and_overwrites_all_existing_targets_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            codex_target = home / ".codex" / "prompts" / "implement_task.md"
            claude_target = home / ".claude" / "commands" / "implement_task.md"
            codex_target.parent.mkdir(parents=True, exist_ok=True)
            claude_target.parent.mkdir(parents=True, exist_ok=True)
            codex_target.write_text("old codex prompt\n", encoding="utf-8")
            claude_target.write_text("old claude prompt\n", encoding="utf-8")
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(["install-prompts", "--cli", "codex,claude"], env={})

            buffer = StringIO()
            with (
                redirect_stdout(buffer),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch("builtins.input", return_value="y") as prompt_mock,
            ):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            rendered = buffer.getvalue()
            self.assertIn("codex: overwritten", rendered)
            self.assertIn("claude: overwritten", rendered)
            self.assertEqual(prompt_mock.call_count, 1)
            prompt_text = prompt_mock.call_args.args[0]
            self.assertIn("Overwrite 2 existing prompt file(s)?", prompt_text)
            self.assertIn("codex", prompt_text)
            self.assertIn("claude", prompt_text)
            for target in (codex_target, claude_target):
                written = target.read_text(encoding="utf-8")
                self.assertTrue(written.startswith("You are implementing real code, end-to-end."))
                self.assertIn("Before any implementation work, run `git add .`", written)
            self.assertEqual(list(home.rglob("*.bak-*")), [])

    def test_install_prompts_decline_aborts_before_any_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            codex_target = home / ".codex" / "prompts" / "implement_task.md"
            claude_target = home / ".claude" / "commands" / "implement_task.md"
            codex_target.parent.mkdir(parents=True, exist_ok=True)
            codex_target.write_text("old codex prompt\n", encoding="utf-8")
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(["install-prompts", "--cli", "codex,claude"], env={})

            buffer = StringIO()
            with (
                redirect_stdout(buffer),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch("builtins.input", return_value="n") as prompt_mock,
            ):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 1)
            self.assertEqual(prompt_mock.call_count, 1)
            self.assertEqual(codex_target.read_text(encoding="utf-8"), "old codex prompt\n")
            self.assertFalse(claude_target.exists())
            self.assertIn("Overwrite declined", buffer.getvalue())

    def test_install_prompts_yes_bypasses_prompt_for_existing_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = home / ".codex" / "prompts" / "implement_task.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("old prompt\n", encoding="utf-8")
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(["install-prompts", "--cli", "codex", "--yes", "--json"], env={})

            buffer = StringIO()
            with redirect_stdout(buffer), patch(
                "builtins.input", side_effect=AssertionError("input() should not be called")
            ):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            by_path = {item["path"]: item for item in payload["results"]}
            self.assertEqual(by_path[str(target)]["status"], "overwritten")
            self.assertIsNone(by_path[str(target)]["backup_path"])
            self.assertTrue((target.parent / "review_task_imp.md").exists())
            self.assertTrue(target.read_text(encoding="utf-8").startswith("You are implementing real code, end-to-end."))

    def test_install_prompts_force_bypasses_prompt_for_existing_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = home / ".codex" / "prompts" / "implement_task.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("old prompt\n", encoding="utf-8")
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(["install-prompts", "--cli", "codex", "--force", "--json"], env={})

            buffer = StringIO()
            with redirect_stdout(buffer), patch(
                "builtins.input", side_effect=AssertionError("input() should not be called")
            ):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            by_path = {item["path"]: item for item in payload["results"]}
            self.assertEqual(by_path[str(target)]["status"], "overwritten")
            self.assertIsNone(by_path[str(target)]["backup_path"])
            self.assertTrue((target.parent / "review_worktree_imp.md").exists())

    def test_install_prompts_json_overwrite_requires_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = home / ".codex" / "prompts" / "implement_task.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("old prompt\n", encoding="utf-8")
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(["install-prompts", "--cli", "codex", "--json"], env={})

            buffer = StringIO()
            with redirect_stdout(buffer), patch(
                "builtins.input", side_effect=AssertionError("input() should not be called")
            ):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 1)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["results"][0]["status"], "failed")
            self.assertIn("Overwrite approval required", payload["results"][0]["message"])
            self.assertIn("--yes or --force", payload["results"][0]["message"])
            self.assertEqual(target.read_text(encoding="utf-8"), "old prompt\n")

    def test_non_json_install_results_hyperlink_paths_when_enabled(self) -> None:
        buffer = _TtyStringIO()
        with redirect_stdout(buffer):
            code = _print_install_results(
                preset="implement_task",
                dry_run=False,
                json_output=False,
                env={"ENVCTL_UI_HYPERLINK_MODE": "on"},
                results=[
                    PromptInstallResult(
                        cli="codex",
                        path="/tmp/prompt.md",
                        status="written",
                        backup_path="/tmp/prompt.md.bak",
                        message="Installed prompt",
                    )
                ],
            )

        self.assertEqual(code, 0)
        rendered = buffer.getvalue()
        self.assertIn("\x1b]8;;file://", rendered)
        self.assertIn("/tmp/prompt.md", strip_ansi(rendered))
        self.assertIn("/tmp/prompt.md.bak", strip_ansi(rendered))

    def test_install_prompts_non_tty_overwrite_requires_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = home / ".codex" / "prompts" / "implement_task.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("old prompt\n", encoding="utf-8")
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(["install-prompts", "--cli", "codex"], env={})

            buffer = StringIO()
            with (
                redirect_stdout(buffer),
                patch("sys.stdin.isatty", return_value=False),
                patch("sys.stdout.isatty", return_value=False),
                patch("builtins.input", side_effect=AssertionError("input() should not be called")),
            ):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 1)
            self.assertIn("Overwrite approval required", buffer.getvalue())
            self.assertIn("--yes or --force", buffer.getvalue())
            self.assertEqual(target.read_text(encoding="utf-8"), "old prompt\n")

    def test_install_prompts_dry_run_existing_target_does_not_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = home / ".codex" / "prompts" / "implement_task.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("old prompt\n", encoding="utf-8")
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(["install-prompts", "--cli", "codex", "--dry-run", "--json"], env={})

            buffer = StringIO()
            with redirect_stdout(buffer), patch(
                "builtins.input", side_effect=AssertionError("input() should not be called")
            ):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            by_path = {item["path"]: item for item in payload["results"]}
            self.assertEqual(by_path[str(target)]["status"], "planned")
            self.assertIsNone(by_path[str(target)]["backup_path"])
            self.assertEqual(target.read_text(encoding="utf-8"), "old prompt\n")

    def test_install_prompts_reports_partial_failure_for_invalid_cli_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "codex,unknown", "--dry-run", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 1)
            payload = json.loads(buffer.getvalue())
            results = payload["results"]
            self.assertEqual(results[0]["cli"], "unknown")
            self.assertEqual(results[0]["status"], "failed")
            self.assertEqual(results[1]["cli"], "codex")
            self.assertEqual(results[1]["status"], "planned")

    def test_install_prompts_rejects_missing_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(["install-prompts", "--json"], env={})

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 1)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["results"][0]["status"], "failed")
            self.assertIn("Missing required --cli", payload["results"][0]["message"])

    def test_install_prompts_rejects_unsupported_preset(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "codex", "--preset", "review_perfect", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 1)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["results"][0]["status"], "failed")
            self.assertIn("Unsupported preset", payload["results"][0]["message"])
            self.assertIn("implement_task", payload["results"][0]["message"])

    def test_template_registry_discovers_built_in_templates_by_filename(self) -> None:
        self.assertIn("implement_task", _available_presets())
        self.assertIn("review_task_imp", _available_presets())
        self.assertIn("review_worktree_imp", _available_presets())
        self.assertIn("continue_task", _available_presets())
        self.assertIn("merge_trees_into_dev", _available_presets())
        self.assertIn("create_plan", _available_presets())
        self.assertIn("implement_plan", _available_presets())
        self.assertEqual(len(_available_presets()), 7)

    def test_install_prompts_can_install_implement_plan_alias(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "codex", "--preset", "implement_plan", "--dry-run", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertEqual(payload["preset"], "implement_plan")
            self.assertEqual(payload["results"][0]["message"], "Would install implement_plan for codex")

    def test_renderers_produce_expected_target_shapes(self) -> None:
        template = _load_template("implement_task")
        codex = _render_codex_template(template)
        claude = _render_claude_template(template)
        opencode = _render_opencode_template(template)

        self.assertEqual(template.name, "implement_task")
        self.assertTrue(codex.startswith("You are implementing real code, end-to-end."))
        self.assertIn("Authoritative spec file: MAIN_TASK.md.", codex)
        self.assertIn("write that content into `MAIN_TASK.md` first", codex)
        self.assertIn(".envctl-commit-message.md", codex)
        self.assertIn("### Envctl pointer ###", codex)
        self.assertIn("boundary after the last successful commit", codex)
        self.assertIn("one complete next commit message", codex)
        self.assertIn("full cumulative set of changes between commits", codex)
        self.assertEqual(claude, codex)
        self.assertEqual(opencode, codex)

        continue_prompt = _load_template("continue_task")
        self.assertIn(".envctl-commit-message.md", continue_prompt.body)
        self.assertIn("### Envctl pointer ###", continue_prompt.body)
        self.assertIn(".envctl-state/worktree-provenance.json", continue_prompt.body)
        self.assertIn("git merge-base HEAD <originating-base>", continue_prompt.body)

        review_prompt = _load_template("review_task_imp")
        self.assertIn(".envctl-commit-message.md", review_prompt.body)
        self.assertIn("### Envctl pointer ###", review_prompt.body)

        review_worktree_prompt = _load_template("review_worktree_imp")
        self.assertEqual(review_worktree_prompt.name, "review_worktree_imp")
        self.assertIn("current local repo directory is the unedited baseline", review_worktree_prompt.body)
        self.assertIn("defaults to the worktree created from the current plan file", review_worktree_prompt.body)
        self.assertIn("unless `$ARGUMENTS` overrides that target", review_worktree_prompt.body)
        self.assertIn("read-only", review_worktree_prompt.body)
        self.assertIn("findings-first", review_worktree_prompt.body)

        merge_prompt = _load_template("merge_trees_into_dev")
        self.assertEqual(merge_prompt.name, "merge_trees_into_dev")
        self.assertIn("Read `MAIN_TASK.md` from branch A and branch B separately.", merge_prompt.body)
        self.assertIn("first merge branch A into `dev`", merge_prompt.body)
        self.assertIn(".envctl-commit-message.md", merge_prompt.body)

        plan_prompt = _load_template("create_plan")
        self.assertNotIn("Changelog entry appended.", plan_prompt.body)

    def test_prompt_templates_no_longer_reference_changelog_backed_commit_defaults(self) -> None:
        implement_prompt = _load_template("implement_task")
        continue_prompt = _load_template("continue_task")
        review_prompt = _load_template("review_task_imp")
        merge_prompt = _load_template("merge_trees_into_dev")

        for prompt in (implement_prompt, continue_prompt, review_prompt, merge_prompt):
            with self.subTest(prompt=prompt.name):
                self.assertNotIn("docs/changelog/{tree_name}_changelog.md", prompt.body)
                self.assertIn("keep `.envctl-commit-message.md` focused on one complete next commit message", prompt.body)
                self.assertIn("full cumulative set of changes between commits", prompt.body)


if __name__ == "__main__":
    unittest.main()
