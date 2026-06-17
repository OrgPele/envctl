from __future__ import annotations

# ruff: noqa: F403,F405
from tests.python.runtime.prompt_install_support_test_support import *


class PromptInstallSupportTemplatesTests(PromptInstallSupportTestCase):
    def test_available_presets_excludes_private_plan_agent_followup_templates(self) -> None:
        presets = _available_presets()

        self.assertIn("implement_task", presets)
        self.assertNotIn("_plan_agent_browser_e2e_followup", presets)
        self.assertNotIn("_plan_agent_pr_review_comments_followup", presets)

    def test_template_registry_discovers_built_in_templates_by_filename(self) -> None:
        self.assertIn("implement_task", _available_presets())
        self.assertIn("review_worktree_imp", _available_presets())
        self.assertIn("continue_task", _available_presets())
        self.assertIn("finalize_task", _available_presets())
        self.assertIn("merge_implementation_branches", _available_presets())
        self.assertIn("create_plan", _available_presets())
        self.assertIn("create_plan_auto_codex", _available_presets())
        self.assertIn("create_plan_auto_opencode", _available_presets())
        self.assertIn("create_plan_auto_omx", _available_presets())
        self.assertNotIn("implement_plan", _available_presets())
        self.assertNotIn("review_task_imp", _available_presets())
        self.assertNotIn("ship_release", _available_presets())
        self.assertEqual(len(_available_presets()), 9)

    def test_create_plan_auto_templates_lock_launch_commands(self) -> None:
        expected = {
            "create_plan_auto_codex": {
                "command": (
                    "ENVCTL_PLAN_AGENT_CODEX_CYCLES=<recommended_codex_cycles> "
                    "envctl --plan <category>/<slug> --cmux --preset implement_task --entire-system "
                    "--headless --new-session"
                ),
                "phrases": (
                    "Use the normal `create_plan` workflow",
                    "shared `implement_task` prompt",
                    "must be run from Codex",
                ),
            },
            "create_plan_auto_opencode": {
                "command": (
                    "envctl --plan <category>/<slug> --cmux --opencode --preset implement_task --entire-system "
                    "--headless --new-session"
                ),
                "phrases": (
                    "Use the normal `create_plan` workflow",
                    "shared `implement_task` prompt",
                    "OpenCode plan-agent launches use the `/ulw-loop` prefix by default",
                ),
            },
            "create_plan_auto_omx": {
                "command": (
                    "envctl --plan <category>/<slug> --omx --ultragoal --preset implement_task "
                    "--entire-system --headless --new-session"
                ),
                "phrases": (
                    "Use the normal `create_plan` workflow",
                    "shared `implement_task` prompt",
                    "OMX-managed launches are Codex-only",
                    "Use `--ralph` explicitly only when the Ralph compatibility workflow is required",
                ),
            },
        }

        for preset, contract in expected.items():
            with self.subTest(preset=preset):
                template = _load_template(preset)
                body = template.body
                self.assertIn("Use the normal `create_plan` workflow", body)
                self.assertIn("Do not implement in the planning session after launch.", body)
                self.assertIn("todo/plans/<category>/<slug>.md", body)
                self.assertIn("removing `todo/plans/` and `.md`", body)
                self.assertIn("attach/reconnect guidance", body)
                self.assertIn(contract["command"], body)
                for phrase in contract["phrases"]:
                    self.assertIn(phrase, body)
                self.assertIn("--headless", body)
                self.assertIn("--new-session", body)
                self.assertIn("--entire-system", body)
                self.assertIn("Use a narrower runtime scope only when the plan explicitly records why full-stack E2E does not apply.", body)

    def test_create_plan_template_requires_bounded_codex_cycle_recommendation(self) -> None:
        body = _load_template("create_plan").body

        self.assertIn("Codex cycle recommendation", body)
        self.assertIn("exactly one integer from `0` through `3`", body)
        self.assertNotIn("exactly one integer from `0` through `8`", body)
        self.assertIn("Prefer the smallest number", body)
        self.assertIn("Rollout / verification", body)

    def test_create_plan_template_requires_browser_e2e_decision(self) -> None:
        body = _load_template("create_plan").body

        self.assertIn("Browser E2E decision", body)
        self.assertIn("browser_e2e_required", body)
        self.assertIn("ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=false", body)
        self.assertIn("ENVCTL_PLAN_AGENT_BROWSER_E2E_ENABLE=true", body)
        self.assertIn("Record both the browser E2E decision and rationale", body)
        self.assertIn("Rollout / verification", body)

    def test_create_plan_templates_do_not_embed_fixed_auto_codex_cycle_command(self) -> None:
        fixed_command = "ENVCTL_PLAN_AGENT_CODEX_CYCLES=4 envctl --plan <category>/<slug>"

        for preset in ("create_plan", "create_plan_auto_codex", "create_plan_auto_omx"):
            with self.subTest(preset=preset):
                self.assertNotIn(fixed_command, _load_template(preset).body)

    def test_renderers_produce_expected_target_shapes(self) -> None:
        template = _load_template("implement_task")
        codex = _render_codex_template(template)
        claude = _render_claude_template(template)
        opencode = _render_opencode_template(template)

        self.assertEqual(template.name, "implement_task")
        self.assertTrue(codex.startswith("You are implementing real code, end-to-end."))
        for phrase in (
            "Authoritative spec file: MAIN_TASK.md.",
            "write it into `MAIN_TASK.md` first",
            "WORKTREE BOUNDARY IS STRICT",
            "Use TDD",
            "git status --short",
            "one complete commit/PR handoff message",
            "Do not write envctl-local commit-message ledger files",
            "envctl test-focused",
            'envctl ship -m "<message>"',
            "`ship` commits, pushes, creates a PR when none exists",
            "waits for target GitHub Tests checks",
            "A successful ship result is silent",
            "Do not run raw `git`, `gh`, or separate commit/PR/status commands",
            "Only inspect PR review comments when `ship` reports actionable review-comment status",
            "envctl --entire-system --headless",
            "envctl --backend --headless",
            "envctl --frontend --headless",
            "envctl --fullstack --headless",
            "envctl --dependencies --headless",
            "envctl stop --entire-system --headless",
            "$browser",
            "Use the injected worktree code-intelligence context when envctl adds one",
            "use `rg` for exact strings",
            "only use Serena, CGC/CodeGraphContext, CodeGraph, or another graph tool",
            "envctl endpoints --project <actual-project-name> --json",
            "envctl qa-user ensure --project <actual-project-name>",
            "envctl playwright --project <actual-project-name> -- <executable> [args...]",
            "Runtime addresses used or produced",
            "Playwright",
            "running service",
        ):
            with self.subTest(prompt="implement_task", phrase=phrase):
                self.assertIn(phrase, codex)
        self.assertNotIn("envctl test-focused --project <current-worktree-name> --dry-run --json", codex)
        self.assertNotIn("Inspect unresolved PR review comments after the PR exists", codex)
        self.assertNotIn(".envctl-commit-message.md", codex)
        self.assertNotIn("### Envctl pointer ###", codex)
        self.assertNotIn("boundary after the last successful commit", codex)
        self.assertLessEqual(len(codex.splitlines()), 105)
        self.assertNotIn("$browser-use", codex)
        self.assertNotEqual(claude, codex)
        self.assertIn("$browser-use", claude)
        self.assertNotEqual(opencode, codex)
        self.assertIn("$browser-use", opencode)

        continue_prompt = _load_template("continue_task")
        for phrase in (
            "current `MAIN_TASK.md`",
            "OLD_TASK_<iteration>.md",
            ".envctl-state/worktree-provenance.json",
            "git merge-base HEAD <originating-base>",
            "one complete commit/PR handoff message",
            "what validation proved",
            "Do not write envctl-local commit-message ledger files",
        ):
            self.assertIn(phrase, continue_prompt.body)
        self.assertLessEqual(len(continue_prompt.body.splitlines()), 80)
        self.assertNotIn(".envctl-commit-message.md", continue_prompt.body)
        self.assertNotIn("### Envctl pointer ###", continue_prompt.body)

        finalize_prompt = _load_template("finalize_task")
        self.assertEqual(finalize_prompt.name, "finalize_task")
        for phrase in (
            "envctl test-focused",
            "envctl test-focused --project <current-worktree-name>",
            "envctl endpoints --project <current-worktree-name> --json",
            "envctl qa-user ensure --project <current-worktree-name>",
            "envctl playwright --project <current-worktree-name> -- <command>",
            "$browser",
            'envctl ship -m "<message>"',
            '`envctl ship --project <current-worktree-name> -m "<message>"`',
            "what validation proved",
            "Do not run raw `git`, `gh`, or separate commit/PR/status commands",
            "A successful ship result is silent",
            "Only inspect PR review comments when `ship` reports actionable review-comment status",
        ):
            self.assertIn(phrase, finalize_prompt.body)
        self.assertLessEqual(len(finalize_prompt.body.splitlines()), 55)
        self.assertNotIn("envctl test-focused --project <current-worktree-name> --dry-run --json", finalize_prompt.body)
        self.assertNotIn("$browser-use", finalize_prompt.body)
        self.assertNotIn("Inspect unresolved PR review comments", finalize_prompt.body)

        intermediate_prompt = _load_template("_plan_agent_intermediate_cycle_completion").body
        self.assertIn('envctl ship -m "<message>"', intermediate_prompt)
        self.assertIn("Success criteria:", intermediate_prompt)
        self.assertIn("what validation proved", intermediate_prompt)
        self.assertIn("PR create/update", intermediate_prompt)
        self.assertIn("return to the shipping lane only when it reports an issue", intermediate_prompt)
        self.assertIn("A successful ship result is silent", intermediate_prompt)
        self.assertLessEqual(len(intermediate_prompt.splitlines()), 12)

        first_cycle_prompt = _load_template("_plan_agent_first_cycle_completion").body
        self.assertIn("Success criteria:", first_cycle_prompt)
        self.assertIn("what validation proved", first_cycle_prompt)
        self.assertIn("A successful ship result is silent", first_cycle_prompt)
        self.assertLessEqual(len(first_cycle_prompt.splitlines()), 12)

        review_comments_prompt = _load_template("_plan_agent_pr_review_comments_followup").body
        self.assertIn('envctl ship -m "<message>"', review_comments_prompt)
        self.assertIn("what validation proved", review_comments_prompt)
        self.assertIn("Inspect unresolved PR review comments", review_comments_prompt)
        self.assertIn("Address every actionable comment", review_comments_prompt)
        self.assertIn("A successful ship result is silent", review_comments_prompt)
        self.assertLessEqual(len(review_comments_prompt.splitlines()), 12)

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

        merge_prompt = _load_template("merge_implementation_branches")
        self.assertEqual(merge_prompt.name, "merge_implementation_branches")
        self.assertIn("Read `MAIN_TASK.md` from branch A and branch B separately.", merge_prompt.body)
        self.assertIn("first merge branch A into the integration branch", merge_prompt.body)
        self.assertIn("Merge target: `integration/<branch-a>-plus-<branch-b>`", merge_prompt.body)
        self.assertNotIn(".envctl-commit-message.md", merge_prompt.body)
        self.assertIn("The final commit/PR handoff message is available inline", merge_prompt.body)

        plan_prompt = _load_template("create_plan")
        self.assertNotIn("Changelog entry appended.", plan_prompt.body)
        self.assertIn("Default to `rg` for exact strings", plan_prompt.body)
        self.assertIn("Use repo-local AGENTS.md/tooling guidance and any injected code-intelligence context", plan_prompt.body)
        self.assertIn("use Serena, CGC/CodeGraphContext, CodeGraph, or another graph tool only when", plan_prompt.body)
        self.assertNotIn("use CodeGraphContext (`cgc`) for repo-wide ownership", plan_prompt.body)
        self.assertNotIn("Do not use the legacy `codegraph` CLI or `.codegraph/` indexes in envctl", plan_prompt.body)
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

    def test_prompt_templates_no_longer_reference_changelog_backed_commit_defaults(self) -> None:
        implement_prompt = _load_template("implement_task")
        continue_prompt = _load_template("continue_task")
        merge_prompt = _load_template("merge_implementation_branches")

        for prompt in (implement_prompt, continue_prompt, merge_prompt):
            with self.subTest(prompt=prompt.name):
                self.assertNotIn("docs/changelog/{tree_name}_changelog.md", prompt.body)
                self.assertIn("pass it inline with `envctl ship -m", prompt.body)
                self.assertIn("Do not run `envctl commit` separately", prompt.body)
                self.assertIn("full cumulative set of changes between commits", prompt.body)

    def test_ai_playbook_documents_prompt_editing_standard(self) -> None:
        body = (Path("docs/user/ai-playbooks.md")).read_text(encoding="utf-8")

        self.assertIn("Prompt editing standard:", body)
        self.assertIn("Put the outcome and source of truth before procedure.", body)
        self.assertIn('`envctl ship -m "<message>"`', body)
        self.assertIn("Cover prompt edits with tests", body)
