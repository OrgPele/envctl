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
            "First, read the relevant code, tests, docs, and existing plans deeply enough to ground the plan before writing anything.",
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
            "2. Review todo/plans/README.md if it exists; otherwise use the nearest relevant plan file(s) in the current repo for depth/format reference without leaving the repo root to hunt for a README elsewhere.",
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
            "explain the supported launch surfaces clearly enough that the user does not need to run `envctl --help` to understand them",
            "Ground the follow-up in the real supported flow",
            "Use these repo-scoped command forms as the source of examples",
            "Multi-launch choices mean separate commands",
            "- default the launch preset to `implement_task`",
            "AI launch choice: `codex`, `opencode`, `omx`, `codex + opencode`, or `codex + omx`",
            "if the selected launch choice includes Codex or OMX-managed Codex, include `recommended Codex cycles: <n>`",
            "## Final response format",
            "1. Path of the plan file created.",
            "2. One-paragraph summary of the plan intent.",
            "3. Files referenced during research (short list).",
            "5. One short approval question asking whether you should run the envctl worktree-and-prompt follow-up now or whether the user wants to run it manually.",
        )

    def test_create_plan_prompt_distinguishes_launch_scope_from_validation(self) -> None:
        self.assertContainsCluster(
            "Treat this as plan-agent scope metadata and dependency-prep intent, not as an instruction for the implementation prompt to start local services or prove the feature through local deployment.",
            'Separately record the validation lane: `envctl test-focused --ship-on-pass "<message>"` by default, which validates and then runs the standard ship workflow including staging via git add, commit, push, PR/check reporting.',
            "Do not record or recommend standalone `envctl test-focused`",
            "If ship returns `deployment_url`, that URL is the deployed website and must be tested thoroughly E2E.",
            'explain that launch-scope flags select the implementation surface for the plan-agent workflow; they do not replace `envctl test-focused --ship-on-pass "<message>"`, `envctl ship` fallback, or deployed PR URL validation',
            "they never justify standalone `envctl test-focused`",
        )


if __name__ == "__main__":
    unittest.main()
