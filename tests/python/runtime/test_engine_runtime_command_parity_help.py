# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.runtime.engine_runtime_command_parity_test_support import *


class EngineRuntimeCommandParityHelpTests(EngineRuntimeCommandParityTestCase):
    def test_parity_manifest_marks_operational_actions_complete(self) -> None:
        manifest_path = REPO_ROOT / "contracts" / "python_engine_parity_manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        for command in ("test", "delete-worktree", "blast-worktree", "pr", "commit", "review", "migrate"):
            self.assertEqual(payload["commands"][command], "python_complete", msg=command)

    def test_list_commands_returns_all_supported_commands(self) -> None:
        runtime = self._runtime()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--list-commands"], env={}))

        self.assertEqual(code, 0)
        output = buffer.getvalue()
        lines = [line.strip() for line in output.strip().split("\n") if line.strip()]

        # Verify all supported commands are present
        expected_commands = {
            "plan",
            "start",
            "restart",
            "resume",
            "stop",
            "stop-all",
            "blast-all",
            "config",
            "dashboard",
            "doctor",
            "test",
            "test-focused",
            "logs",
            "clear-logs",
            "health",
            "errors",
            "delete-worktree",
            "blast-worktree",
            "self-destruct-worktree",
            "pr",
            "commit",
            "ship",
            "review",
            "migrate",
            "migrate-hooks",
            "endpoints",
            "qa-user",
            "playwright",
            "supabase-user",
            "install-prompts",
            "codex-tmux",
            "list-commands",
            "list-targets",
            "list-trees",
            "session",
            "show-config",
            "show-state",
            "explain-startup",
            "ensure-worktree",
            "preflight",
            "help",
            "debug-pack",
            "debug-report",
            "debug-last",
        }
        self.assertEqual(set(lines), expected_commands)
        self.assertEqual(len(lines), 44, "Should have exactly 44 commands")

    def test_public_command_inventory_matches_supported_commands(self) -> None:
        self.assertEqual(
            set(list_supported_commands()),
            {
                "start",
                "plan",
                "resume",
                "dashboard",
                "config",
                "doctor",
                "ensure-worktree",
                "endpoints",
                "qa-user",
                "playwright",
                "migrate-hooks",
                "supabase-user",
                "install-prompts",
                "codex-tmux",
                "debug-pack",
                "debug-report",
                "debug-last",
                "help",
                "list-commands",
                "list-targets",
                "list-trees",
                "show-config",
                "show-state",
                "explain-startup",
                "preflight",
                "test",
                "test-focused",
                "pr",
                "commit",
                "ship",
                "review",
                "migrate",
                "logs",
                "clear-logs",
                "health",
                "errors",
                "delete-worktree",
                "blast-worktree",
                "self-destruct-worktree",
                "stop",
                "restart",
                "stop-all",
                "blast-all",
                "session",
            },
        )

    def test_help_output_lists_same_command_inventory(self) -> None:
        runtime = self._runtime()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--help"], env={}))

        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("envctl - run, inspect, test, and ship repo services/worktrees", output)
        self.assertIn("Usage:", output)
        self.assertIn("Command families:", output)
        self.assertIn("Workflow commands (may start services or open interactive flows):", output)
        self.assertIn("Specific action commands (non-interactive/headless by default):", output)
        self.assertIn("Inspection and diagnostics:", output)
        self.assertIn("Targeting and runtime scopes:", output)
        self.assertIn("Examples:", output)
        self.assertIn("Get focused help:", output)
        self.assertIn("envctl <command> --help", output)
        self.assertIn("envctl help <command>", output)
        self.assertIn("pass --interactive to opt back into prompts", output)

        command_line = next(line for line in output.splitlines() if line.startswith("  all commands: "))
        help_commands = {item.strip() for item in command_line.split("all commands: ", 1)[1].split(",") if item.strip()}
        self.assertEqual(help_commands, set(list_supported_commands()))

    def test_all_supported_commands_have_focused_help(self) -> None:
        runtime = self._runtime()
        for command in list_supported_commands():
            if command == "help":
                continue
            with self.subTest(command=command):
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = runtime.dispatch(parse_route([command, "--help"], env={}))

                output = buffer.getvalue()
                self.assertEqual(code, 0)
                self.assertIn(f"envctl {command}", output)
                self.assertIn("What it does:", output)
                self.assertIn("Usage:", output)
                self.assertIn("Examples:", output)

    def test_action_command_help_explains_headless_default_and_interactive_opt_in(self) -> None:
        runtime = self._runtime()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["pr", "--help"], env={}))

        output = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("envctl pr", output)
        self.assertIn("Default interactivity:", output)
        self.assertIn("headless by default", output)
        self.assertIn("--interactive", output)
        self.assertIn("--pr-base", output)

    def test_test_focused_help_mentions_default_run_and_dry_run_mode(self) -> None:
        runtime = self._runtime()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["test-focused", "--help"], env={}))

        output = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("--dry-run", output)
        self.assertIn("runs the focused commands by default", output)
        self.assertIn("test-focused", output)

    def test_ship_help_mentions_pr_conflicts_and_check_payloads(self) -> None:
        runtime = self._runtime()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["ship", "--help"], env={}))

        output = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("creates a PR when needed and reuses or updates an existing PR", output)
        self.assertIn("predicts merge conflicts", output)
        self.assertIn("conflicting files, messages, and resolution steps", output)
        self.assertIn("rendered names start with Tests", output)
        self.assertIn("failing_checks and pending_checks", output)
        self.assertIn("JSON is the default", output)
        self.assertIn("--human", output)

    def test_workflow_command_help_explains_when_headless_is_optional(self) -> None:
        runtime = self._runtime()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["start", "--help"], env={}))

        output = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("envctl start", output)
        self.assertIn("Default interactivity:", output)
        self.assertIn("interactive-capable", output)
        self.assertIn("--headless", output)

    def test_help_output_for_plan_is_command_specific(self) -> None:
        runtime = self._runtime()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["--plan", "--help"], env={}))

        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("envctl plan", output)
        self.assertIn("--dry-run", output)
        self.assertIn("--ulw", output)
        self.assertIn("--omx --ultragoal", output)
        self.assertIn("--omx --ralph", output)
        self.assertIn("preview selected/reused/created worktrees without mutating", output)

    def test_help_prefix_forms_are_command_specific(self) -> None:
        runtime = self._runtime()
        for argv, expected in (
            (["help", "pr"], "envctl pr"),
            (["--help", "pr"], "envctl pr"),
            (["help", "--plan"], "envctl plan"),
            (["--help", "--command", "pr"], "envctl pr"),
        ):
            with self.subTest(argv=argv):
                route = parse_route(argv, env={})
                self.assertEqual(route.command, "help")
                buffer = StringIO()
                with redirect_stdout(buffer):
                    code = runtime.dispatch(route)

                self.assertEqual(code, 0)
                self.assertIn(expected, buffer.getvalue())

    def test_help_output_for_codex_tmux_is_command_specific(self) -> None:
        runtime = self._runtime()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["codex-tmux", "--help"], env={}))

        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("envctl codex-tmux", output)
        self.assertIn("--dry-run [--json]", output)
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", output)

    def test_help_output_for_install_prompts_is_command_specific(self) -> None:
        runtime = self._runtime()
        buffer = StringIO()
        with redirect_stdout(buffer):
            code = runtime.dispatch(parse_route(["install-prompts", "--help"], env={}))

        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("envctl install-prompts", output)
        self.assertIn("~/.codex/skills", output)
        self.assertIn("manual $envctl-", output)

    def test_generated_parity_manifest_matches_repository_file(self) -> None:
        manifest_path = REPO_ROOT / "contracts" / "python_engine_parity_manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        generated_at = str(payload["generated_at"])
        completed = subprocess.run(
            [
                "python3",
                str(REPO_ROOT / "scripts" / "generate_python_engine_parity_manifest.py"),
                "--repo",
                str(REPO_ROOT),
                "--stdout",
                "--timestamp",
                generated_at,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        generated = json.loads(completed.stdout)
        self.assertEqual(generated, payload)
