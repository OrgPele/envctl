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
    _target_path,
    PromptInstallResult,
    resolve_codex_direct_prompt_body,
    resolve_opencode_direct_prompt_body,
    run_install_prompts_command,
)
from envctl_engine.test_output.parser_base import strip_ansi


_CREATE_PLAN_AUTO_PRESETS = (
    "create_plan_auto_codex",
    "create_plan_auto_opencode",
    "create_plan_auto_omx",
)


class _TtyStringIO(StringIO):
    def isatty(self) -> bool:
        return True


class PromptInstallSupportTests(unittest.TestCase):
    def _target(self, *, cli: str, preset: str, home: Path) -> Path:
        return _target_path(cli_name=cli, preset=preset, home=home, env={"HOME": str(home)})

    def _skill_target(self, *, home: Path, preset: str) -> Path:
        skill_name = f"envctl-{preset.replace('_', '-')}"
        if preset == "review_task_imp":
            skill_name = "envctl-review-task"
        if preset == "review_worktree_imp":
            skill_name = "envctl-review-worktree"
        return home / ".codex" / "skills" / skill_name / "SKILL.md"

    @staticmethod
    def _skill_body_wrapper(body: str) -> str:
        return (
            '---\n'
            'name: "envctl-test"\n'
            'description: "test"\n'
            '---\n\n'
            '# Test\n\n'
            '<!-- ENVCTL_DIRECT_PROMPT_BODY_START -->\n'
            + body
            + '\n<!-- ENVCTL_DIRECT_PROMPT_BODY_END -->\n'
        )

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
                str(self._target(cli="claude", preset=preset, home=Path(tmpdir))) for preset in expected_presets
            ] + [
                str(self._target(cli="opencode", preset=preset, home=Path(tmpdir))) for preset in expected_presets
            ]
            self.assertEqual([item["path"] for item in payload["results"]], expected_paths)
            self.assertEqual(
                [item["cli"] for item in payload["results"]],
                ["claude"] * len(expected_presets)
                + ["opencode"] * len(expected_presets),
            )
            self.assertTrue(all(item["status"] == "planned" for item in payload["results"]))
            self.assertFalse(self._skill_target(home=Path(tmpdir), preset="implement_task").exists())
            self.assertFalse((Path(tmpdir) / ".claude" / "commands" / "implement_task.md").exists())
            self.assertFalse((Path(tmpdir) / ".config" / "opencode" / "commands" / "implement_task.md").exists())

    def test_available_presets_excludes_private_plan_agent_followup_templates(self) -> None:
        presets = _available_presets()

        self.assertIn("implement_task", presets)
        self.assertNotIn("_plan_agent_browser_e2e_followup", presets)
        self.assertNotIn("_plan_agent_pr_review_comments_followup", presets)

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
            self.assertEqual(payload["results"], [])
            self.assertIn("skill_results", payload)
            self.assertEqual(
                [item["path"] for item in payload["skill_results"]],
                [str(self._skill_target(home=Path(tmpdir), preset=preset)) for preset in expected_presets],
            )
            self.assertIn("guidance", payload)
            self.assertTrue(all(entry["installed_as"] == "skill" for entry in payload["guidance"]))

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
            self.assertIn("Would install envctl-implement-task for codex from preset implement_task", rendered)
            self.assertIn("Would install envctl-review-task for codex from preset review_task_imp", rendered)
            self.assertIn("Would install envctl-review-worktree for codex from preset review_worktree_imp", rendered)
            self.assertIn("Would install envctl-continue-task for codex from preset continue_task", rendered)
            self.assertIn("Would install envctl-finalize-task for codex from preset finalize_task", rendered)
            self.assertIn("Would install envctl-merge-trees-into-dev for codex from preset merge_trees_into_dev", rendered)
            self.assertIn("Would install envctl-create-plan for codex from preset create_plan", rendered)
            self.assertIn("Would install envctl-create-plan-auto-codex for codex from preset create_plan_auto_codex", rendered)
            self.assertIn(
                "Would install envctl-create-plan-auto-opencode for codex from preset create_plan_auto_opencode",
                rendered,
            )
            self.assertIn("Would install envctl-create-plan-auto-omx for codex from preset create_plan_auto_omx", rendered)
            self.assertIn("Would install envctl-implement-plan for codex from preset implement_plan", rendered)
            self.assertIn("Would install envctl-ship-release for codex from preset ship_release", rendered)
            self.assertEqual(rendered.count("codex: planned "), 12)

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
                []
            )

    def test_install_prompts_prompts_once_and_overwrites_all_existing_targets_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            codex_target = self._skill_target(home=home, preset="implement_task")
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
            self.assertIn("codex: written", rendered)
            self.assertIn("claude: overwritten", rendered)
            self.assertEqual(prompt_mock.call_count, 1)
            prompt_text = prompt_mock.call_args.args[0]
            self.assertIn("Overwrite 2 existing prompt file(s)?", prompt_text)
            self.assertIn("claude", prompt_text)
            self.assertIn("codex", prompt_text)
            for target in (claude_target,):
                written = target.read_text(encoding="utf-8")
                self.assertTrue(written.startswith("You are implementing real code, end-to-end."))
                self.assertIn("Before any implementation work, run `git add .`", written)
            self.assertEqual(list(home.rglob("*.bak-*")), [])

    def test_install_prompts_overwrite_prompt_hyperlinks_existing_paths_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = self._skill_target(home=home, preset="implement_task")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("old codex prompt\n", encoding="utf-8")
            runtime = SimpleNamespace(env={"HOME": tmpdir, "ENVCTL_UI_HYPERLINK_MODE": "on"})
            route = parse_route(["install-prompts", "--cli", "codex"], env={})

            buffer = _TtyStringIO()
            with (
                redirect_stdout(buffer),
                patch("sys.stdin.isatty", return_value=True),
                patch("sys.stdout.isatty", return_value=True),
                patch("builtins.input", return_value="n") as prompt_mock,
            ):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 1)
            prompt_text = prompt_mock.call_args.args[0]
            self.assertIn("\x1b]8;;file://", prompt_text)
            plain = strip_ansi(prompt_text)
            self.assertIn("Overwrite 1 existing prompt file(s)?", plain)
            self.assertIn(f"- codex: {target}", plain)

    def test_install_prompts_decline_aborts_before_any_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            codex_target = self._skill_target(home=home, preset="implement_task")
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
            target = self._skill_target(home=home, preset="implement_task")
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
            by_path = {item["path"]: item for item in payload["skill_results"]}
            self.assertEqual(by_path[str(target)]["status"], "overwritten")
            self.assertIsNone(by_path[str(target)]["backup_path"])
            self.assertTrue((target.parent.parent / "envctl-review-task" / "SKILL.md").exists())
            self.assertIn("<!-- ENVCTL_DIRECT_PROMPT_BODY_START -->", target.read_text(encoding="utf-8"))

    def test_install_prompts_force_bypasses_prompt_for_existing_targets(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = self._skill_target(home=home, preset="implement_task")
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
            by_path = {item["path"]: item for item in payload["skill_results"]}
            self.assertEqual(by_path[str(target)]["status"], "overwritten")
            self.assertIsNone(by_path[str(target)]["backup_path"])
            self.assertTrue((target.parent.parent / "envctl-review-worktree" / "SKILL.md").exists())

    def test_install_prompts_json_overwrite_requires_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = self._skill_target(home=home, preset="implement_task")
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

    def test_non_json_install_results_print_guidance_for_codex_skills(self) -> None:
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = _print_install_results(
                preset="implement_task",
                dry_run=False,
                json_output=False,
                env={},
                results=[],
                skill_results=[
                    PromptInstallResult(
                        cli="codex",
                        kind="skill",
                        path="/tmp/.codex/skills/envctl-implement-task/SKILL.md",
                        status="written",
                        backup_path=None,
                        message="Installed skill",
                    )
                ],
            )

        self.assertEqual(code, 0)
        rendered = buffer.getvalue()
        self.assertIn("manual invocation $envctl-implement-task", rendered)
        self.assertIn("envctl-managed plan launches submit the rendered workflow automatically", rendered)

    def test_install_prompts_non_tty_overwrite_requires_explicit_approval(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = self._skill_target(home=home, preset="implement_task")
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
            target = self._skill_target(home=home, preset="implement_task")
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
            by_path = {item["path"]: item for item in payload["skill_results"]}
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
            self.assertEqual(payload["skill_results"][0]["cli"], "codex")
            self.assertEqual(payload["skill_results"][0]["status"], "planned")

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

    def test_install_prompts_installs_codex_skills_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "codex", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertIn("skill_results", payload)
            self.assertEqual(payload["results"], [])
            self.assertEqual(payload["skill_results"][0]["kind"], "skill")

    def test_install_prompts_installs_codex_skills_with_legacy_feature_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(
                env={
                    "HOME": tmpdir,
                    "ENVCTL_EXPERIMENTAL_CODEX_SKILLS": "true",
                }
            )
            route = parse_route(
                ["install-prompts", "--cli", "codex", "--preset", "implement_task", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            self.assertIn("skill_results", payload)
            self.assertEqual(len(payload["skill_results"]), 1)
            skill_result = payload["skill_results"][0]
            self.assertEqual(skill_result["kind"], "skill")
            target = self._skill_target(home=Path(tmpdir), preset="implement_task")
            self.assertEqual(skill_result["path"], str(target))
            written = target.read_text(encoding="utf-8")
            self.assertIn('name: "envctl-implement-task"', written)
            frontmatter = written.split("---", 2)[1]
            self.assertIn("envctl service-scope flags", frontmatter)
            self.assertIn("--backend", frontmatter)
            self.assertIn("Playwright", frontmatter)
            self.assertIn("Use this skill explicitly with `$envctl-implement-task`.", written)
            self.assertIn("<!-- ENVCTL_DIRECT_PROMPT_BODY_START -->", written)
            self.assertIn("You are implementing real code, end-to-end.", written)
            openai_yaml = target.parent / "agents" / "openai.yaml"
            self.assertTrue(openai_yaml.exists())
            rendered_yaml = openai_yaml.read_text(encoding="utf-8")
            self.assertIn("allow_implicit_invocation: false", rendered_yaml)
            self.assertIn("envctl --backend --headless", rendered_yaml)
            self.assertIn("default to `envctl --entire-system --headless`", rendered_yaml)
            self.assertIn("Use `envctl --fullstack --headless` only", rendered_yaml)
            self.assertIn("Use backend only for backend-confined changes", rendered_yaml)
            self.assertIn("Use frontend only for frontend-confined changes", rendered_yaml)
            self.assertIn("run the final relevant validation after the code is complete", rendered_yaml)
            self.assertIn("actual addresses/URLs for started dependencies, backend, and frontend", rendered_yaml)
            self.assertIn("kill the scope you started", rendered_yaml)
            self.assertIn("offer to start it again for human verification", rendered_yaml)
            self.assertIn("Playwright", rendered_yaml)

    def test_template_registry_discovers_built_in_templates_by_filename(self) -> None:
        self.assertIn("implement_task", _available_presets())
        self.assertIn("review_task_imp", _available_presets())
        self.assertIn("review_worktree_imp", _available_presets())
        self.assertIn("continue_task", _available_presets())
        self.assertIn("finalize_task", _available_presets())
        self.assertIn("merge_trees_into_dev", _available_presets())
        self.assertIn("create_plan", _available_presets())
        self.assertIn("create_plan_auto_codex", _available_presets())
        self.assertIn("create_plan_auto_opencode", _available_presets())
        self.assertIn("create_plan_auto_omx", _available_presets())
        self.assertIn("implement_plan", _available_presets())
        self.assertIn("ship_release", _available_presets())
        self.assertEqual(len(_available_presets()), 12)

    def test_create_plan_auto_templates_lock_launch_commands(self) -> None:
        expected = {
            "create_plan_auto_codex": {
                "command": (
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES=<recommended_codex_cycles> "
                    "envctl --plan <category>/<slug> --cmux --entire-system --headless --new-session"
                ),
                "phrases": (
                    "recommended_codex_cycles=<n>",
                    "exactly one integer from `0` through `8`",
                    "uses the `implement_task` preset through the current plan-agent default",
                    "envctl queues the rendered follow-up prompts/messages",
                    "envctl itself does not run `git`, `gh`, `envctl commit`, or `envctl pr`",
                ),
            },
            "create_plan_auto_opencode": {
                "command": (
                    "envctl --plan <category>/<slug> --cmux --opencode --entire-system "
                    "--headless --new-session"
                ),
                "phrases": (
                    "OpenCode plan-agent launches use the `/ulw-loop` prefix by default",
                    "Codex cycle settings are intentionally ignored for this surface",
                    "do not silently fall back to Codex",
                ),
            },
            "create_plan_auto_omx": {
                "command": "envctl --plan <category>/<slug> --omx --ultragoal --entire-system --headless --new-session",
                "phrases": (
                    "Recommended Codex-equivalent cycles: <n>",
                    "informational",
                    "OMX-managed launches are Codex-only",
                    "`--ultragoal` is the default persistence workflow for this surface",
                    "use `--ralph` explicitly when you need the Ralph compatibility workflow",
                    "envctl can queue the same Codex follow-up cycle workflow",
                ),
            },
        }

        for preset, contract in expected.items():
            with self.subTest(preset=preset):
                template = _load_template(preset)
                body = template.body
                self.assertIn("This is the auto-launch variant of `create_plan.md`", body)
                self.assertIn(
                    "if the base research/planning contract changes, update this file in the same commit",
                    body,
                )
                self.assertIn("Do not implement code. Only research and write the plan file.", body)
                self.assertIn("Automatic envctl follow-up", body)
                self.assertIn("todo/plans/<category>/<slug>.md", body)
                self.assertIn("remove the `todo/plans/` prefix and the `.md` suffix", body)
                self.assertIn("Confirm `<category>` is one of `broken`, `features`, `refactoring`, or `implementations`", body)
                self.assertIn("Confirm the file exists on disk", body)
                self.assertIn("Run the launch command from the repo root", body)
                self.assertIn("If selector derivation fails", body)
                self.assertIn("If the envctl launch command exits non-zero", body)
                self.assertIn("attach/reconnect guidance", body)
                self.assertIn("must not begin implementing in the original planning session", body)
                self.assertIn(contract["command"], body)
                for phrase in contract["phrases"]:
                    self.assertIn(phrase, body)
                self.assertIn("--headless", body)
                self.assertIn("--new-session", body)
                self.assertIn("Launch scope default", body)
                self.assertIn("--entire-system", body)
                self.assertIn("backend-only", body)
                self.assertIn("--only-backend", body)
                self.assertIn("frontend-only", body)
                self.assertIn("--only-frontend", body)
                self.assertIn("no runtime infrastructure", body)
                self.assertIn("--no-infra", body)
                self.assertNotIn("Do not run `envctl` unless the user explicitly says yes", body)

    def test_create_plan_templates_require_bounded_codex_cycle_recommendation(self) -> None:
        for preset in ("create_plan", "create_plan_auto_codex", "create_plan_auto_omx"):
            with self.subTest(preset=preset):
                body = _load_template(preset).body

                self.assertIn("Codex cycle recommendation", body)
                self.assertIn("exactly one integer from `0` through `8`", body)
                self.assertIn("Prefer the smallest number", body)
                self.assertIn("Rollout / verification", body)

    def test_create_plan_templates_do_not_embed_fixed_auto_codex_cycle_command(self) -> None:
        fixed_command = "ENVCTL_PLAN_AGENT_CODEX_CYCLES=4 envctl --plan <category>/<slug>"

        for preset in ("create_plan", "create_plan_auto_codex", "create_plan_auto_omx"):
            with self.subTest(preset=preset):
                self.assertNotIn(fixed_command, _load_template(preset).body)

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
            self.assertEqual(payload["results"], [])
            self.assertEqual(payload["skill_results"][0]["message"], "Would install envctl-implement-plan for codex from preset implement_plan")

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
        self.assertIn("envctl test-focused --project <current-worktree-name>", codex)
        self.assertIn("envctl test-focused --project <current-worktree-name> --dry-run --json", codex)
        self.assertIn("prefer `envctl ship --project <current-worktree-name> --json`", codex)
        self.assertIn("fall back to `envctl commit`, `envctl pr`, and `gh pr checks`", codex)
        self.assertIn("returns the PR URL, current GitHub check state, and merge-conflict details", codex)
        self.assertIn("does not wait for pending checks by itself", codex)
        self.assertIn("Inspect unresolved PR review comments", codex)
        self.assertIn("address all actionable comments", codex)
        self.assertIn("wait for final PR confirmation", codex)
        self.assertIn("PR status and URL", codex)
        self.assertIn("full cumulative set of changes between commits", codex)
        self.assertIn("envctl --backend --headless", codex)
        self.assertIn("envctl --frontend --headless", codex)
        self.assertIn("envctl --fullstack --headless", codex)
        self.assertIn("envctl --dependencies --headless", codex)
        self.assertIn("envctl --entire-system --headless", codex)
        self.assertIn("envctl stop --entire-system --headless", codex)
        self.assertIn("Codex skills and envctl validation helpers", codex)
        self.assertIn("$browser", codex)
        self.assertNotIn("$browser-use", codex)
        self.assertIn("envctl endpoints --project <current-worktree-name> --json", codex)
        self.assertIn("envctl qa-user ensure --project <current-worktree-name>", codex)
        self.assertIn("envctl playwright --project <current-worktree-name> -- <command>", codex)
        self.assertIn("Default to `envctl --entire-system --headless`", codex)
        self.assertIn("Use `envctl --fullstack --headless` only", codex)
        self.assertIn("Use backend only", codex)
        self.assertIn("Use frontend only", codex)
        self.assertIn("kill the exact scope you started", codex)
        self.assertIn("offer to start it again for human verification", codex)
        self.assertIn("At the end of every implementation, run the final relevant validation yourself", codex)
        self.assertIn("actual addresses for every available dependency plus backend and frontend", codex)
        self.assertIn("Runtime addresses used or produced during validation: dependencies, backend, and frontend", codex)
        self.assertIn("Playwright", codex)
        self.assertIn("running service", codex)
        self.assertNotEqual(claude, codex)
        self.assertIn("$browser-use", claude)
        self.assertNotEqual(opencode, codex)
        self.assertIn("$browser-use", opencode)

        continue_prompt = _load_template("continue_task")
        self.assertIn(".envctl-commit-message.md", continue_prompt.body)
        self.assertIn("### Envctl pointer ###", continue_prompt.body)
        self.assertIn(".envctl-state/worktree-provenance.json", continue_prompt.body)
        self.assertIn("git merge-base HEAD <originating-base>", continue_prompt.body)

        finalize_prompt = _load_template("finalize_task")
        self.assertEqual(finalize_prompt.name, "finalize_task")
        self.assertIn("run `envctl test-focused --project <current-worktree-name>`", finalize_prompt.body)
        self.assertIn("Use `envctl test-focused --project <current-worktree-name> --dry-run --json`", finalize_prompt.body)
        self.assertIn("envctl endpoints --project <current-worktree-name> --json", finalize_prompt.body)
        self.assertIn("envctl qa-user ensure --project <current-worktree-name>", finalize_prompt.body)
        self.assertIn("envctl playwright --project <current-worktree-name> -- <command>", finalize_prompt.body)
        self.assertIn("$browser", finalize_prompt.body)
        self.assertNotIn("$browser-use", finalize_prompt.body)
        self.assertIn("Run `envctl ship --project <current-worktree-name> --json`", finalize_prompt.body)
        self.assertIn("Fall back to `envctl commit`, `envctl pr`, and GitHub CLI checks", finalize_prompt.body)
        self.assertIn("returns current status and merge-conflict details", finalize_prompt.body)
        self.assertIn("then wait for GitHub checks separately when they are pending", finalize_prompt.body)
        self.assertIn("Inspect unresolved PR review comments", finalize_prompt.body)
        self.assertIn("address all actionable comments", finalize_prompt.body)

        review_prompt = _load_template("review_task_imp")
        self.assertIn(".envctl-commit-message.md", review_prompt.body)
        self.assertIn("### Envctl pointer ###", review_prompt.body)
        self.assertIn("original plan file", review_prompt.body)
        self.assertIn(".envctl-state/worktree-provenance.json", review_prompt.body)
        self.assertNotIn("Authoritative source of truth: `MAIN_TASK.md`", review_prompt.body)
        self.assertNotIn("Verify functionality matches MAIN_TASK.md exactly", review_prompt.body)

        review_worktree_prompt = _load_template("review_worktree_imp")
        self.assertEqual(review_worktree_prompt.name, "review_worktree_imp")
        self.assertIn("current local repo directory is the unedited baseline", review_worktree_prompt.body)
        self.assertIn("defaults to the worktree created from the current plan file", review_worktree_prompt.body)
        self.assertIn("Launch arguments:\n$ARGUMENTS", review_worktree_prompt.body)
        self.assertIn("Treat only the first path-like token as the explicit worktree override", review_worktree_prompt.body)
        self.assertIn("If reviewer notes include an original plan file path, use that first", review_worktree_prompt.body)
        self.assertIn("read `.envctl-state/worktree-provenance.json`", review_worktree_prompt.body)
        self.assertIn("Do not start with broad repo exploration before reading the original plan file", review_worktree_prompt.body)
        self.assertIn("use that bundle as the primary review guide", review_worktree_prompt.body)
        self.assertNotIn("MAIN_TASK.md", review_worktree_prompt.body)
        self.assertNotIn("OLD_TASK_", review_worktree_prompt.body)
        self.assertIn("read-only", review_worktree_prompt.body)
        self.assertIn("findings-first", review_worktree_prompt.body)

        merge_prompt = _load_template("merge_trees_into_dev")
        self.assertEqual(merge_prompt.name, "merge_trees_into_dev")
        self.assertIn("Read `MAIN_TASK.md` from branch A and branch B separately.", merge_prompt.body)
        self.assertIn("first merge branch A into `dev`", merge_prompt.body)
        self.assertIn(".envctl-commit-message.md", merge_prompt.body)

        ship_release_prompt = _load_template("ship_release")
        self.assertEqual(ship_release_prompt.name, "ship_release")
        self.assertIn("shipping a production release end-to-end", ship_release_prompt.body)
        self.assertIn("Create and publish the GitHub release", ship_release_prompt.body)
        self.assertIn("Final output must include", ship_release_prompt.body)

        plan_prompt = _load_template("create_plan")
        self.assertNotIn("Changelog entry appended.", plan_prompt.body)
        self.assertIn("envctl --headless --plan <selector>", plan_prompt.body)
        self.assertIn(
            "cd <repo> && envctl --plan <selector> --tmux --opencode",
            plan_prompt.body,
        )
        self.assertIn(
            "default to the cmux launcher when cmux is installed",
            plan_prompt.body,
        )
        self.assertIn(
            "cd <repo> && ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n> envctl --plan <selector> --tmux",
            plan_prompt.body,
        )
        self.assertIn(
            "cd <repo> && ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n> envctl --plan <selector> --omx",
            plan_prompt.body,
        )
        self.assertIn(
            "cd <repo> && envctl --plan <selector> --omx --ultragoal",
            plan_prompt.body,
        )
        self.assertIn(
            "cd <repo> && envctl --plan <selector> --omx --ralph",
            plan_prompt.body,
        )
        self.assertIn(
            "cd <repo> && envctl --plan <selector> --omx --team",
            plan_prompt.body,
        )
        self.assertIn(
            "envctl creates or reuses the tmux session/window itself",
            plan_prompt.body,
        )
        self.assertIn(
            "envctl asks OMX to create the managed detached tmux/Codex session",
            plan_prompt.body,
        )
        self.assertIn(
            "same OMX-managed launch, but the first submitted prompt enters the Ultragoal workflow",
            plan_prompt.body,
        )
        self.assertIn(
            "same OMX-managed launch, but the first submitted prompt enters the Ralph compatibility workflow",
            plan_prompt.body,
        )
        self.assertIn(
            "same OMX-managed launch, but the first submitted prompt enters the Team workflow",
            plan_prompt.body,
        )
        self.assertIn(
            "envctl stays non-interactive and prints follow-up/attach guidance instead of taking over the current terminal",
            plan_prompt.body,
        )
        self.assertIn(
            "create a fresh cmux surface, tmux session, or OMX-managed session instead of attaching to an existing one",
            plan_prompt.body,
        )
        self.assertIn(
            "whenever you show a follow-up command, also explain in plain language what happens when that exact command runs",
            plan_prompt.body,
        )
        self.assertIn(
            "whether envctl only prints guidance or actually launches a session",
            plan_prompt.body,
        )
        self.assertIn(
            "spell out what envctl creates or syncs, what CLI or session it starts, what prompt preset it submits",
            plan_prompt.body,
        )
        self.assertIn(
            "`opencode` applies only to the cmux/tmux launcher paths today; OMX-managed launches are Codex-only",
            plan_prompt.body,
        )
        self.assertIn(
            "cd <repo> && envctl --plan <selector> --tmux --opencode --entire-system --headless",
            plan_prompt.body,
        )
        self.assertIn(
            "cd <repo> && ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n> envctl --plan <selector> --tmux --entire-system --headless",
            plan_prompt.body,
        )
        self.assertNotIn(
            "cd <repo> && envctl --plan <selector> --tmux --entire-system",
            plan_prompt.body,
        )
        self.assertNotIn(
            "cd <repo> && envctl --plan <selector> --omx --entire-system",
            plan_prompt.body,
        )
        self.assertIn("--new-session", plan_prompt.body)
        self.assertIn("prepends `/ulw-loop` to the first submitted prompt by default", plan_prompt.body)
        self.assertIn("use `tmux attach -t <session>` rather than `tmux switch-client -t <session>`", plan_prompt.body)
        self.assertIn(
            "create a fresh cmux surface, tmux session, or OMX-managed session instead of attaching to an existing one",
            plan_prompt.body,
        )
        self.assertIn("when you execute envctl launch commands yourself from an AI session, always add `--new-session`", plan_prompt.body)
        self.assertIn("do not surface the internal `--new-session` default in the user-facing approval question", plan_prompt.body)
        self.assertIn("if the user selects `codex + opencode`, run or show both repo-scoped commands explicitly as two separate envctl invocations", plan_prompt.body)
        self.assertIn("if the user selects `codex + omx`, run or show both repo-scoped commands explicitly as two separate envctl invocations", plan_prompt.body)
        self.assertIn(
            "AI launch choice: `codex`, `opencode`, `omx`, `codex + opencode`, or `codex + omx` (multi-launch choices mean run the separate repo-scoped commands one after another)",
            plan_prompt.body,
        )
        self.assertIn("recommended Codex cycles: <n>", plan_prompt.body)
        self.assertIn("selected launch choice includes Codex or OMX-managed Codex", plan_prompt.body)
        self.assertIn("if the selected launch choice does not involve Codex, say that the Codex cycle count setting is ignored", plan_prompt.body)
        self.assertNotIn("CMUX=true", plan_prompt.body)
        self.assertNotIn("ENVCTL_PLAN_AGENT_CLI=", plan_prompt.body)
        self.assertNotIn("ENVCTL_PLAN_AGENT_TERMINALS_ENABLE", plan_prompt.body)
        self.assertIn("--tmux --opencode", plan_prompt.body)
        self.assertNotIn("--tmux --codex", plan_prompt.body)
        self.assertNotIn("AI CLI choice: `codex`, `opencode`, or `both`", plan_prompt.body)
        self.assertIn(
            "one tmux Codex command with `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>` "
            "and one OMX-managed Codex command with `ENVCTL_PLAN_AGENT_CODEX_CYCLES=<n>`",
            plan_prompt.body,
        )
        self.assertIn("do not tell the user to manually type `/prompts:implement_task`, `$envctl-implement-task`, or any other in-session command", plan_prompt.body)
        self.assertIn("keep research narrow", plan_prompt.body)
        self.assertIn("CURRENT-REPO BOUNDARY IS ALSO STRICT FOR RESEARCH", plan_prompt.body)
        self.assertIn("Do not run parent-directory or sibling-repo searches such as `find ..`", plan_prompt.body)
        self.assertIn("If the user explicitly asks for a light/quick/minimal planning pass", plan_prompt.body)
        self.assertIn("Review todo/plans/README.md if it exists", plan_prompt.body)
        self.assertIn("Launch scope default", plan_prompt.body)
        self.assertIn("--entire-system", plan_prompt.body)
        self.assertIn("backend-only", plan_prompt.body)
        self.assertIn("--only-backend", plan_prompt.body)
        self.assertIn("frontend-only", plan_prompt.body)
        self.assertIn("--only-frontend", plan_prompt.body)
        self.assertIn("no runtime infrastructure", plan_prompt.body)
        self.assertIn("--no-infra", plan_prompt.body)

    def test_install_prompts_writes_ship_release_to_envctl_codex_prompt_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "codex", "--preset", "ship_release", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            expected = self._skill_target(home=Path(tmpdir), preset="ship_release")
            self.assertEqual(payload["skill_results"][0]["path"], str(expected))
            self.assertTrue(expected.exists())
            self.assertIn("shipping a production release end-to-end", expected.read_text(encoding="utf-8"))

    def test_install_prompts_writes_create_plan_auto_codex_skills_with_markers(self) -> None:
        for preset in _CREATE_PLAN_AUTO_PRESETS:
            with self.subTest(preset=preset), tempfile.TemporaryDirectory() as tmpdir:
                runtime = SimpleNamespace(env={"HOME": tmpdir})
                route = parse_route(
                    ["install-prompts", "--cli", "codex", "--preset", preset, "--json"],
                    env={},
                )

                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = run_install_prompts_command(runtime, route)

                self.assertEqual(code, 0)
                payload = json.loads(buffer.getvalue())
                expected = self._skill_target(home=Path(tmpdir), preset=preset)
                self.assertEqual(payload["skill_results"][0]["path"], str(expected))
                self.assertTrue(expected.exists())
                written = expected.read_text(encoding="utf-8")
                skill_name = f"envctl-{preset.replace('_', '-')}"
                self.assertIn(f'name: "{skill_name}"', written)
                self.assertIn(f"Use this skill explicitly with `${skill_name}`.", written)
                self.assertIn("<!-- ENVCTL_DIRECT_PROMPT_BODY_START -->", written)
                self.assertIn("<!-- ENVCTL_DIRECT_PROMPT_BODY_END -->", written)
                self.assertIn("Automatic envctl follow-up", written)
                openai_yaml = expected.parent / "agents" / "openai.yaml"
                self.assertTrue(openai_yaml.exists())
                self.assertIn("allow_implicit_invocation: false", openai_yaml.read_text(encoding="utf-8"))

    def test_install_prompts_writes_create_plan_auto_opencode_command_with_default_ulw_loop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime = SimpleNamespace(env={"HOME": tmpdir})
            route = parse_route(
                ["install-prompts", "--cli", "opencode", "--preset", "create_plan_auto_opencode", "--json"],
                env={},
            )

            buffer = StringIO()
            with redirect_stdout(buffer):
                code = run_install_prompts_command(runtime, route)

            self.assertEqual(code, 0)
            payload = json.loads(buffer.getvalue())
            expected = self._target(cli="opencode", preset="create_plan_auto_opencode", home=Path(tmpdir))
            self.assertEqual(payload["results"][0]["path"], str(expected))
            self.assertTrue(expected.exists())
            written = expected.read_text(encoding="utf-8")
            self.assertIn(
                "envctl --plan <category>/<slug> --cmux --opencode --entire-system "
                "--headless --new-session",
                written,
            )
            self.assertIn("Codex cycle settings are intentionally ignored for this surface", written)

    def test_resolve_codex_direct_prompt_body_prefers_user_installed_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = self._target(cli="codex", preset="ship_release", home=home)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("Custom release instructions\n", encoding="utf-8")

            resolved = resolve_codex_direct_prompt_body(preset="ship_release", env={"HOME": tmpdir})

            self.assertEqual(resolved, "Custom release instructions\n")

    def test_resolve_codex_direct_prompt_body_uses_legacy_codex_prompt_when_new_target_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            legacy_target = home / ".codex" / "prompts" / "ship_release.md"
            legacy_target.parent.mkdir(parents=True, exist_ok=True)
            legacy_target.write_text("Legacy release instructions\n", encoding="utf-8")

            resolved = resolve_codex_direct_prompt_body(preset="ship_release", env={"HOME": tmpdir})

            self.assertEqual(resolved, "Legacy release instructions\n")

    def test_resolve_codex_direct_prompt_body_prefers_new_target_over_legacy_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = self._target(cli="codex", preset="ship_release", home=home)
            legacy_target = home / ".codex" / "prompts" / "ship_release.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            legacy_target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("New envctl prompt\n", encoding="utf-8")
            legacy_target.write_text("Legacy release instructions\n", encoding="utf-8")

            resolved = resolve_codex_direct_prompt_body(preset="ship_release", env={"HOME": tmpdir})

            self.assertEqual(resolved, "New envctl prompt\n")

    def test_resolve_codex_direct_prompt_body_replaces_installed_skill_argument_sentinel(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = self._skill_target(home=home, preset="create_plan_auto_codex")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                self._skill_body_wrapper(
                    "Inputs:\nadditional user instructions supplied with the invoking prompt\n"
                    "Keep `$ARGUMENTS` literal in prose.\n"
                ),
                encoding="utf-8",
            )

            resolved = resolve_codex_direct_prompt_body(
                preset="create_plan_auto_codex",
                env={"HOME": tmpdir},
                arguments="Auto launch Codex after planning",
            )

            self.assertIn("Auto launch Codex after planning", resolved)
            self.assertNotIn("additional user instructions supplied with the invoking prompt", resolved)
            self.assertIn("Keep `$ARGUMENTS` literal in prose.", resolved)
            self.assertEqual(resolved.count("$ARGUMENTS"), 1)

    def test_resolve_codex_direct_prompt_body_appends_arguments_for_stale_installed_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = self._skill_target(home=home, preset="review_worktree_imp")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                self._skill_body_wrapper(
                    "Review prompt body without the generated argument sentinel.\n"
                ),
                encoding="utf-8",
            )

            resolved = resolve_codex_direct_prompt_body(
                preset="review_worktree_imp",
                env={"HOME": tmpdir},
                arguments='Project: feature-a-1\nReview bundle: "/tmp/review.md"',
            )

            self.assertIn("Review prompt body without the generated argument sentinel.", resolved)
            self.assertIn('Review bundle: "/tmp/review.md"', resolved)

    def test_resolve_codex_direct_prompt_body_supports_create_plan_auto_codex(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            resolved = resolve_codex_direct_prompt_body(
                preset="create_plan_auto_codex",
                env={"HOME": tmpdir},
                arguments="Auto launch Codex after planning",
            )

        self.assertIn("Automatic envctl follow-up", resolved)
        self.assertIn("recommended_codex_cycles=<n>", resolved)
        self.assertIn("ENVCTL_PLAN_AGENT_CODEX_CYCLES=<recommended_codex_cycles>", resolved)
        self.assertIn("exactly one integer from `0` through `8`", resolved)
        self.assertIn("Auto launch Codex after planning", resolved)

    def test_resolve_opencode_direct_prompt_body_supports_create_plan_auto_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            resolved = resolve_opencode_direct_prompt_body(
                preset="create_plan_auto_opencode",
                env={"HOME": tmpdir},
                arguments="Auto launch OpenCode ULW after planning",
            )

        self.assertIn("Automatic envctl follow-up", resolved)
        self.assertIn("--cmux --opencode --entire-system --headless --new-session", resolved)
        self.assertIn("Auto launch OpenCode ULW after planning", resolved)

    def test_resolve_opencode_direct_prompt_body_keeps_browser_use_skill_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            resolved = resolve_opencode_direct_prompt_body(preset="implement_task", env={"HOME": tmpdir})

        self.assertIn("$browser-use", resolved)

    def test_resolve_opencode_direct_prompt_body_does_not_double_browser_use_in_user_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = self._target(cli="opencode", preset="implement_task", home=home)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("Use $browser-use for browser validation.\n", encoding="utf-8")

            resolved = resolve_opencode_direct_prompt_body(preset="implement_task", env={"HOME": tmpdir})

            self.assertEqual(resolved, "Use $browser-use for browser validation.\n")

    def test_resolve_codex_direct_prompt_body_only_replaces_standalone_arguments_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = self._target(cli="codex", preset="review_worktree_imp", home=home)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                "Inputs:\n$ARGUMENTS\nKeep `$ARGUMENTS` literal in prose.\n",
                encoding="utf-8",
            )

            resolved = resolve_codex_direct_prompt_body(
                preset="review_worktree_imp",
                env={"HOME": tmpdir},
                arguments="Review bundle: /tmp/review.md\nWorktree directory: /tmp/tree",
            )

            self.assertIn("Review bundle: /tmp/review.md\nWorktree directory: /tmp/tree", resolved)
            self.assertIn("Keep `$ARGUMENTS` literal in prose.", resolved)
            self.assertEqual(resolved.count("$ARGUMENTS"), 1)

    def test_resolve_opencode_direct_prompt_body_prefers_user_installed_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = self._target(cli="opencode", preset="implement_task", home=home)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("Direct OpenCode prompt body\n", encoding="utf-8")

            resolved = resolve_opencode_direct_prompt_body(preset="implement_task", env={"HOME": tmpdir})

            self.assertEqual(resolved, "Direct OpenCode prompt body\n")

    def test_resolve_opencode_direct_prompt_body_renders_arguments_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            home = Path(tmpdir)
            target = self._target(cli="opencode", preset="review_worktree_imp", home=home)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                "Inputs:\n$ARGUMENTS\nKeep `$ARGUMENTS` literal in prose.\n",
                encoding="utf-8",
            )

            resolved = resolve_opencode_direct_prompt_body(
                preset="review_worktree_imp",
                env={"HOME": tmpdir},
                arguments="Review bundle: /tmp/review.md\nWorktree directory: /tmp/tree",
            )

            self.assertIn("Review bundle: /tmp/review.md\nWorktree directory: /tmp/tree", resolved)
            self.assertIn("Keep `$ARGUMENTS` literal in prose.", resolved)
            self.assertEqual(resolved.count("$ARGUMENTS"), 1)

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
