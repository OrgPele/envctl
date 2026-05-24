from __future__ import annotations

# ruff: noqa: F403,F405
from tests.python.runtime.prompt_install_support_test_support import *


class PromptInstallSupportDirectPromptTests(PromptInstallSupportTestCase):
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

        self.assertIn("Use the normal `create_plan` workflow", resolved)
        self.assertIn("ENVCTL_PLAN_AGENT_CODEX_CYCLES=<recommended_codex_cycles>", resolved)
        self.assertIn("--preset implement_task", resolved)
        self.assertIn("Auto launch Codex after planning", resolved)

    def test_resolve_opencode_direct_prompt_body_supports_create_plan_auto_opencode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            resolved = resolve_opencode_direct_prompt_body(
                preset="create_plan_auto_opencode",
                env={"HOME": tmpdir},
                arguments="Auto launch OpenCode ULW after planning",
            )

        self.assertIn("Use the normal `create_plan` workflow", resolved)
        self.assertIn("--cmux --opencode --preset implement_task --entire-system --headless --new-session", resolved)
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
