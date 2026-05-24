from __future__ import annotations

# ruff: noqa: F403,F405
from tests.python.runtime.prompt_install_support_test_support import *


class PromptInstallSupportInstallFlowTests(PromptInstallSupportTestCase):
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
            self.assertIn("Would install envctl-review-worktree for codex from preset review_worktree_imp", rendered)
            self.assertIn("Would install envctl-continue-task for codex from preset continue_task", rendered)
            self.assertIn("Would install envctl-finalize-task for codex from preset finalize_task", rendered)
            self.assertIn(
                "Would install envctl-merge-implementation-branches for codex from preset merge_implementation_branches",
                rendered,
            )
            self.assertIn("Would install envctl-create-plan for codex from preset create_plan", rendered)
            self.assertIn("Would install envctl-create-plan-auto-codex for codex from preset create_plan_auto_codex", rendered)
            self.assertIn(
                "Would install envctl-create-plan-auto-opencode for codex from preset create_plan_auto_opencode",
                rendered,
            )
            self.assertIn("Would install envctl-create-plan-auto-omx for codex from preset create_plan_auto_omx", rendered)
            self.assertNotIn("implement_plan", rendered)
            self.assertNotIn("review_task_imp", rendered)
            self.assertNotIn("ship_release", rendered)
            self.assertEqual(rendered.count("codex: planned "), 9)

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
            self.assertTrue((target.parent.parent / "envctl-review-worktree" / "SKILL.md").exists())
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
