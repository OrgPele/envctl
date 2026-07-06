# ruff: noqa: F403,F405
from __future__ import annotations

from tests.python.planning.plan_agent_launch_support_test_support import *


class PlanAgentLaunchReadinessTests(PlanAgentLaunchSupportTestCase):
    def test_opencode_ready_screen_accepts_loaded_composer_layout(self) -> None:
        screen = '  ┃  Ask anything... "Fix broken tests"\n  ctrl+p commands\n  ~/repo  ⊙ 3 MCP /status    1.2.27\n'
        self.assertTrue(terminal_screen._screen_looks_ready("opencode", screen))

    def test_codex_ready_screen_requires_boot_to_finish(self) -> None:
        loading = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "• Booting MCP server: playwright (0s • esc to interrupt)\n"
            "› Explain this codebase\n"
        )
        model_loading = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     loading   /model to change             │\n"
            "│ directory: ~/repo                                 │\n"
            "› $envctl-implement-task\n"
        )
        ready = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.115.0)                        │\n"
            "│ model:     gpt-5.4 high   fast   /model to change │\n"
            "│ directory: ~/repo                                 │\n"
            "› Explain this codebase\n"
        )
        self.assertFalse(_screen_looks_ready("codex", loading))
        self.assertFalse(_screen_looks_ready("codex", model_loading))
        self.assertTrue(_screen_looks_ready("codex", ready))

    def test_ai_cli_ready_window_allows_slower_opencode_startup(self) -> None:
        self.assertEqual(config._cli_ready_delay_seconds("codex"), 5.0)
        self.assertEqual(config._cli_ready_delay_seconds("opencode"), 15.0)

    def test_opencode_ready_screen_rejects_loading_text_even_with_prompt_glyphs(self) -> None:
        screen = "Loading workspace...\n  ›\n"
        self.assertFalse(_screen_looks_ready("opencode", screen))

    def test_opencode_ready_screen_rejects_plain_shell_prompt_glyph(self) -> None:
        screen = "$ cd repo\n❯\n"
        self.assertFalse(_screen_looks_ready("opencode", screen))

    def test_opencode_ready_screen_rejects_stale_ready_scrollback_followed_by_shell_failure(self) -> None:
        screen = (
            '  ┃  Ask anything... "Fix broken tests"\n'
            "  ctrl+p commands\n"
            "  ~/repo /status\n"
            "zsh: command not found: opencode\n"
            "$ "
        )
        self.assertFalse(_screen_looks_ready("opencode", screen))

    def test_opencode_prompt_submit_screen_waits_for_single_selected_command(self) -> None:
        pending = (
            "  ┃ /implement_task                                                   ┃\n"
            "  ┃ /implement_task.bak-20260313-192914                               ┃\n"
            "  ┃ /implement_task.bak-20260315-173140                               ┃\n"
            "  ┃                                                                 \n"
            "  ┃  /implement_task                                                 \n"
        )
        ready = (
            "  ┃                                                                 \n"
            "  ┃  /implement_task                                                 \n"
            "  ┃                                                                 \n"
            "  ┃  Sisyphus (Ultraworker)                                          \n"
        )
        broken = "  ┃ No matching items ┃\n  ┃  /implement_task/implement_task\n"
        self.assertFalse(_prompt_submit_screen_looks_ready("opencode", pending, "/implement_task"))
        self.assertFalse(_prompt_submit_screen_looks_ready("opencode", broken, "/implement_task"))
        self.assertTrue(_prompt_submit_screen_looks_ready("opencode", ready, "/implement_task"))

    def test_codex_prompt_picker_accepts_skill_selector(self) -> None:
        screen = (
            "╭───────────────────────────────────────────────────╮\n"
            "│ >_ OpenAI Codex (v0.142.5)                        │\n"
            "› $envctl-continue-task\n"
            "\n"
            "  Envctl Continue Task  [Skill] Resume an incomplete envctl implementation pass\n"
            "\n"
            "  Press enter to insert or esc to close\n"
        )

        self.assertTrue(terminal_screen._prompt_picker_screen_looks_ready("codex", screen, "$envctl-continue-task"))

    def test_opencode_post_submit_rejects_unchanged_composer(self) -> None:
        prompt = "/ulw-loop\n\nImplement task"
        unchanged = "  ┃  /ulw-loop\n  ┃\n  ┃  Implement task\n  ctrl+p commands\n  ~/repo /status\n"
        self.assertFalse(terminal_screen._post_submit_screen_looks_accepted("opencode", unchanged, prompt))

    def test_opencode_post_submit_rejects_unknown_screen(self) -> None:
        self.assertFalse(terminal_screen._post_submit_screen_looks_accepted("opencode", "shell prompt\n$ ", "/ulw-loop"))

    def test_opencode_post_submit_accepts_busy_or_cleared_screen(self) -> None:
        prompt = "/ulw-loop\n\nImplement task"
        busy = "Sisyphus is working...\nEsc to interrupt\n"
        cleared = '  ┃  Ask anything... "Follow up"\n  ctrl+p commands\n  ~/repo /status\n'
        self.assertTrue(terminal_screen._post_submit_screen_looks_accepted("opencode", busy, prompt))
        self.assertTrue(terminal_screen._post_submit_screen_looks_accepted("opencode", cleared, prompt))

    def test_opencode_post_submit_accepts_busy_screen_with_prompt_history(self) -> None:
        prompt = "/ulw-loop\n\nImplement task"
        busy_with_history = "  ┃  /ulw-loop\n  ┃\n  ┃  Implement task\nSisyphus is working...\nEsc to interrupt\n"

        self.assertTrue(terminal_screen._post_submit_screen_looks_accepted("opencode", busy_with_history, prompt))

    def test_opencode_active_screen_rejects_generic_shell_output(self) -> None:
        shell_ctrl_c = "Run this command and press Ctrl+C to stop it.\n$ "
        shell_working = "Tests are working as expected.\n$ "

        self.assertFalse(_screen_looks_active("opencode", shell_ctrl_c))
        self.assertFalse(_screen_looks_active("opencode", shell_working))

    def test_opencode_active_screen_requires_opencode_activity_context(self) -> None:
        screen = "Sisyphus is working...\nEsc to interrupt\n"

        self.assertTrue(_screen_looks_active("opencode", screen))

    def test_ai_cli_failure_excerpt_redacts_sensitive_values(self) -> None:
        result = launch_support.AiCliReadyResult(
            ready=False,
            reason="opencode_ready_timeout",
            screen_excerpt=terminal_screen._screen_excerpt(
                "API_KEY=super-secret\n"
                "https://user:password@example.test/path\n"
                "SESSION_TOKEN=abc123\n"
                "Authorization: Bearer bearer-secret\n"
                "export SESSION_TOKEN space-secret\n"
                "API_KEY another-secret\n"
            ),
        )

        rendered = terminal_screen._format_ai_cli_ready_failure(result)

        self.assertIn("<redacted>", rendered)
        self.assertNotIn("super-secret", rendered)
        self.assertNotIn("user:password", rendered)
        self.assertNotIn("abc123", rendered)
        self.assertNotIn("bearer-secret", rendered)
        self.assertNotIn("space-secret", rendered)
        self.assertNotIn("another-secret", rendered)
