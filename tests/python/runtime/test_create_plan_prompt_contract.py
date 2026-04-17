from __future__ import annotations

import unittest

from envctl_engine.runtime.prompt_install_support import _load_template


class CreatePlanPromptContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.prompt = _load_template("create_plan")
        cls.body = cls.prompt.body

    def assertContainsCluster(self, *snippets: str) -> None:
        for snippet in snippets:
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, self.body)

    def test_create_plan_prompt_requires_planning_not_implementation(self) -> None:
        self.assertEqual(self.prompt.name, "create_plan")
        self.assertContainsCluster(
            "You are creating an implementation plan, not changing code.",
            "First, read the relevant code, tests, docs, and existing plans in depth before writing anything.",
            "Do not implement code. Only research and write the plan file.",
            "- Do not drift into implementation work.",
        )

    def test_create_plan_prompt_enforces_repo_and_plan_path_boundaries(self) -> None:
        self.assertContainsCluster(
            "WORKTREE BOUNDARY IS STRICT: MAKE ALL FILE EDITS ONLY INSIDE THE CURRENT CHECKED-OUT WORKTREE / REPO ROOT.",
            "You may read outside the current worktree ONLY when genuinely needed for historical/reference context",
            "- Always write plan files to the repo root todo/plans/ (never inside tree worktrees).",
            "- Place the plan in todo/plans/<category>/<slug>.md at the repo root where <category> is one of: broken, features, refactoring, implementations.",
            "- Keep nesting to two levels max (todo/plans/<category>/<file>.md).",
        )

    def test_create_plan_prompt_includes_required_research_and_plan_sections(self) -> None:
        self.assertContainsCluster(
            "## Required research (do before writing)",
            "2. Review todo/plans/ README and at least one relevant plan file for depth/format.",
            "4. Inspect the current behavior in code: key files, key functions, and call paths.",
            "7. Capture evidence (file paths + function names) to ground the plan.",
            "## Plan file structure (must follow)",
            "- ## Goals / non-goals / assumptions (if relevant)",
            "- ## Goal (user experience)",
            "- ## Business logic and data model mapping",
            "- ## Current behavior (verified in code)",
            "- ## Root cause(s) / gaps",
            "- ## Tests (add these)",
            "- ## Rollout / verification",
            "- ## Definition of done",
            "- ## Risk register (trade‑offs or missing tests)",
        )

    def test_create_plan_prompt_describes_required_final_response_and_envctl_follow_up(self) -> None:
        self.assertContainsCluster(
            "## Optional envctl follow-up",
            "- After completing the required final response items, ask exactly one final approval question",
            "- use an explicit selector for the created plan with `envctl --headless --plan <selector>`",
            'derive the cmux workspace name dynamically from the current repo root directory name as `"<repo-name> implementation"`',
            "- default the launch preset to `implement_task`",
            "- AI CLI: `codex`",
            "- Codex cycles: `2`",
            "## Final response format",
            "1. Path of the plan file created.",
            "2. One-paragraph summary of the plan intent.",
            "3. Files referenced during research (short list).",
            "5. One final approval question asking whether you should run the envctl worktree-and-prompt follow-up now",
        )


if __name__ == "__main__":
    unittest.main()
