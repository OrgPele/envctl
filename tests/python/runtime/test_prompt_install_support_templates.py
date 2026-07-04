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
                self.assertIn(
                    "it is not an instruction to prove the feature by starting local services",
                    body,
                )
                self.assertIn("## Success criteria", body)
                self.assertIn("## Final response", body)
                self.assertNotIn("## Final Response", body)
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
        self.assertIn("Authoritative spec file: MAIN_TASK.md.", codex)
        self.assertIn("write that content into `MAIN_TASK.md` first", codex)
        self.assertNotIn(".envctl-commit-message.md", codex)
        self.assertNotIn("### Envctl pointer ###", codex)
        self.assertNotIn("boundary after the last successful commit", codex)
        self.assertIn("one complete commit/PR handoff message", codex)
        self.assertIn("what your validation actually did and proved", codex)
        self.assertIn("manual checks a human should still run to truly confirm it works", codex)
        self.assertIn("Do not write envctl-local commit-message ledger files", codex)
        self.assertIn('envctl test-focused --ship-on-pass "<message>"', codex)
        self.assertIn("including staging intended changes via git add", codex)
        self.assertIn("Do not run manual staging commands such as `git add .`", codex)
        self.assertIn("Inspect the baseline with `git status --short`; do not stage files manually", codex)
        self.assertIn("follow AGENTS.md for the combined focused validation-and-handoff workflow", codex)
        self.assertIn("Do not run standalone `envctl test-focused`", codex)
        self.assertIn("Use extra repo test commands only when the focused plan recommends them", codex)
        self.assertNotIn("envctl test-focused --project <current-worktree-name> --dry-run --json", codex)
        self.assertIn("Follow the AGENTS.md ship workflow", codex)
        self.assertIn("Full-stack PR-URL E2E delivery lane", codex)
        self.assertIn("frontend and backend surfaces", codex)
        self.assertIn("deployed PR URL", codex)
        self.assertNotIn("Run bare `envctl ship` from inside the current worktree/project directory", codex)
        self.assertNotIn("returns JSON by default with the PR URL", codex)
        self.assertNotIn("`pr_created`, `operation_statuses`, `checks_state`", codex)
        self.assertNotIn("A successful ship result is silent", codex)
        self.assertIn("Only inspect PR review comments when `ship` reports actionable review-comment status", codex)
        self.assertNotIn("Inspect unresolved PR review comments after the PR exists", codex)
        self.assertIn("PR status and URL", codex)
        self.assertIn("full cumulative set of changes between commits", codex)
        self.assertIn("Do not start or deploy a local envctl runtime as the default proof path", codex)
        self.assertIn("single envctl local validation-and-handoff command", codex)
        self.assertIn("Start local envctl services only when the authoritative task", codex)
        self.assertIn("the final browser-visible proof is the deployed PR URL", codex)
        self.assertIn("## Handoff", codex)
        self.assertNotIn("Default to `envctl --entire-system --headless`", codex)
        self.assertNotIn("envctl --backend --headless", codex)
        self.assertNotIn("envctl --frontend --headless", codex)
        self.assertNotIn("envctl --fullstack --headless", codex)
        self.assertNotIn("envctl --dependencies --headless", codex)
        self.assertNotIn("envctl --entire-system --headless", codex)
        self.assertIn("Tooling and validation context", codex)
        self.assertIn("$browser", codex)
        self.assertNotIn("$browser-use", codex)
        self.assertIn("Follow the active AGENTS.md and any injected worktree code-intelligence context", codex)
        self.assertIn("Use graph or symbol tooling only when it is configured", codex)
        self.assertNotIn("use CodeGraphContext (`cgc`) for repo-wide ownership", codex)
        self.assertNotIn("Do not use the legacy `codegraph` CLI or `.codegraph/` indexes in envctl", codex)
        self.assertNotIn("envctl endpoints --project <actual-project-name> --json", codex)
        self.assertNotIn("envctl qa-user ensure --project <actual-project-name>", codex)
        self.assertNotIn("envctl playwright --project <actual-project-name>", codex)
        self.assertIn("stop exactly what you started before final handoff", codex)
        self.assertIn("At the end of every implementation, run the final relevant validation yourself", codex)
        self.assertIn("If no runtime was started, say so", codex)
        self.assertIn("Runtime addresses used or produced during validation: dependencies, backend, and frontend", codex)
        self.assertIn("Playwright", codex)
        self.assertIn("running target", codex)
        self.assertNotEqual(claude, codex)
        self.assertIn("$browser-use", claude)
        self.assertNotEqual(opencode, codex)
        self.assertIn("$browser-use", opencode)

        continue_prompt = _load_template("continue_task")
        self.assertIn("## Success criteria", continue_prompt.body)
        self.assertIn("The new `MAIN_TASK.md` contains only remaining work", continue_prompt.body)
        self.assertIn("one complete commit/PR handoff message", continue_prompt.body)
        self.assertIn("what your validation actually did and proved", continue_prompt.body)
        self.assertIn("manual checks a human should still run to truly confirm it works", continue_prompt.body)
        self.assertNotIn(".envctl-commit-message.md", continue_prompt.body)
        self.assertNotIn("### Envctl pointer ###", continue_prompt.body)
        self.assertIn("Do not write envctl-local commit-message ledger files", continue_prompt.body)
        self.assertIn(".envctl-state/worktree-provenance.json", continue_prompt.body)
        self.assertIn("git merge-base HEAD <originating-base>", continue_prompt.body)

        finalize_prompt = _load_template("finalize_task")
        self.assertEqual(finalize_prompt.name, "finalize_task")
        self.assertIn("## Success criteria", finalize_prompt.body)
        self.assertIn("only when a local runtime is already running or the task/test harness explicitly requires one", finalize_prompt.body)
        self.assertIn("as the single envctl local validation-and-handoff pass", finalize_prompt.body)
        self.assertIn("deployed PR URL E2E validation is an additional post-PR lane", finalize_prompt.body)
        self.assertIn("Use additional repo-specific test commands only when diagnosing a failure", finalize_prompt.body)
        self.assertIn("include `--project <current-worktree-name>` on that same combined command", finalize_prompt.body)
        self.assertIn("Do not run standalone `envctl test-focused` first or repeat it afterward", finalize_prompt.body)
        self.assertNotIn("envctl test-focused --project <current-worktree-name> --dry-run --json", finalize_prompt.body)
        self.assertNotIn("envctl endpoints --project <current-worktree-name> --json", finalize_prompt.body)
        self.assertNotIn("envctl qa-user ensure --project <current-worktree-name>", finalize_prompt.body)
        self.assertNotIn("envctl playwright --project <current-worktree-name>", finalize_prompt.body)
        self.assertIn("$browser", finalize_prompt.body)
        self.assertNotIn("$browser-use", finalize_prompt.body)
        self.assertIn("Use the injected worktree code-intelligence context if envctl added one", finalize_prompt.body)
        self.assertIn("use `rg` for exact strings", finalize_prompt.body)
        self.assertIn("do not assume Serena, CodeGraph, or any other graph tool exists", finalize_prompt.body)
        self.assertNotIn("CodeGraphContext (`cgc`) for repo-wide ownership", finalize_prompt.body)
        self.assertNotIn("Do not use the legacy `codegraph` CLI or `.codegraph/` indexes in envctl", finalize_prompt.body)
        self.assertIn("Follow AGENTS.md for the ship workflow", finalize_prompt.body)
        self.assertIn("one complete commit/PR handoff message", finalize_prompt.body)
        self.assertIn('envctl test-focused --ship-on-pass "<message>"', finalize_prompt.body)
        self.assertIn("including staging intended changes via git add", finalize_prompt.body)
        self.assertIn("what your validation actually did and proved", finalize_prompt.body)
        self.assertIn("manual checks a human should still run to truly confirm it works", finalize_prompt.body)
        self.assertNotIn("Run bare `envctl ship` from inside the current worktree/project directory", finalize_prompt.body)
        self.assertNotIn("returns JSON by default with current status", finalize_prompt.body)
        self.assertNotIn("`pr_created`, `operation_statuses`, `checks_state`", finalize_prompt.body)
        self.assertNotIn("A successful ship result is silent", finalize_prompt.body)
        self.assertIn("Only inspect PR review comments when `ship` reports actionable review-comment status", finalize_prompt.body)
        self.assertNotIn("Inspect unresolved PR review comments", finalize_prompt.body)

        intermediate_prompt = _load_template("_plan_agent_intermediate_cycle_completion").body
        self.assertIn("## Ship contract", intermediate_prompt)
        self.assertIn('envctl test-focused --ship-on-pass "<message>"', intermediate_prompt)
        self.assertIn('Then fall back to `envctl ship -m "<message>"`', intermediate_prompt)
        self.assertIn("including staging intended changes via git add", intermediate_prompt)
        self.assertIn("Do not substitute localhost validation for deployed PR URL validation", intermediate_prompt)
        self.assertIn("Build the message as a commit/PR handoff message", intermediate_prompt)
        self.assertIn("what your validation actually did and proved", intermediate_prompt)
        self.assertIn("manual checks a human should still run to truly confirm it works", intermediate_prompt)
        self.assertIn("instead of a separate validation, git add, commit, push, and PR flow", intermediate_prompt)
        self.assertIn("Follow AGENTS.md for the ship workflow", intermediate_prompt)
        self.assertNotIn("creates a PR when none exists", intermediate_prompt)
        self.assertNotIn("`pr_created`, `operation_statuses`, `checks_state`", intermediate_prompt)
        self.assertNotIn("A successful ship result is silent", intermediate_prompt)

        first_cycle_prompt = _load_template("_plan_agent_first_cycle_completion").body
        self.assertIn("## Ship contract", first_cycle_prompt)
        self.assertIn('envctl test-focused --ship-on-pass "<message>"', first_cycle_prompt)
        self.assertIn("including staging intended changes via git add", first_cycle_prompt)
        self.assertIn("Do not substitute localhost validation for deployed PR URL validation", first_cycle_prompt)
        self.assertIn("Build the message as a commit/PR handoff message", first_cycle_prompt)
        self.assertIn("what your validation actually did and proved", first_cycle_prompt)
        self.assertIn("manual checks a human should still run to truly confirm it works", first_cycle_prompt)
        self.assertIn("Follow AGENTS.md for the ship workflow", first_cycle_prompt)
        self.assertNotIn("A successful ship result is silent", first_cycle_prompt)

        review_comments_prompt = _load_template("_plan_agent_pr_review_comments_followup").body
        self.assertIn("## Comment triage", review_comments_prompt)
        self.assertIn("## Ship contract", review_comments_prompt)
        self.assertIn('envctl test-focused --ship-on-pass "<message>"', review_comments_prompt)
        self.assertIn("separate validation, git add, commit, push, and PR commands", review_comments_prompt)
        self.assertIn("Build the message as a commit/PR handoff message", review_comments_prompt)
        self.assertIn("what your validation actually did and proved", review_comments_prompt)
        self.assertIn("manual checks a human should still run to truly confirm it works", review_comments_prompt)
        self.assertIn("Inspect unresolved PR review comments", review_comments_prompt)
        self.assertIn("address all actionable comments", review_comments_prompt)
        self.assertIn("Follow AGENTS.md for the ship workflow", review_comments_prompt)
        self.assertNotIn("A successful ship result is silent", review_comments_prompt)

        browser_e2e_prompt = _load_template("_plan_agent_browser_e2e_followup").body
        self.assertIn("## Objective", browser_e2e_prompt)
        self.assertIn("## URL source", browser_e2e_prompt)
        self.assertIn("## Validation steps", browser_e2e_prompt)
        self.assertIn("## Final response", browser_e2e_prompt)
        self.assertIn("conventional deployment URL", browser_e2e_prompt)
        self.assertIn("not from the PR body", browser_e2e_prompt)
        self.assertIn("never use it as the source for the browser URL", browser_e2e_prompt)
        self.assertIn("not automatable from this environment", browser_e2e_prompt)

        review_worktree_prompt = _load_template("review_worktree_imp")
        self.assertEqual(review_worktree_prompt.name, "review_worktree_imp")
        self.assertIn("## Success criteria", review_worktree_prompt.body)
        self.assertIn("Findings are grounded in the target worktree diff", review_worktree_prompt.body)
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
        self.assertIn("## Success criteria", merge_prompt.body)
        self.assertIn("Every conflict is resolved from product and code intent", merge_prompt.body)
        self.assertIn("Read `MAIN_TASK.md` from branch A and branch B separately.", merge_prompt.body)
        self.assertIn("first merge branch A into the integration branch", merge_prompt.body)
        self.assertIn("Merge target: `integration/<branch-a>-plus-<branch-b>`", merge_prompt.body)
        self.assertNotIn(".envctl-commit-message.md", merge_prompt.body)
        self.assertIn("The final commit/PR handoff message is available inline", merge_prompt.body)

        plan_prompt = _load_template("create_plan")
        self.assertNotIn("Changelog entry appended.", plan_prompt.body)
        self.assertIn("Default to `rg` for exact strings", plan_prompt.body)
        self.assertIn("Use repo-local AGENTS.md/tooling guidance and any injected code-intelligence context", plan_prompt.body)
        self.assertIn("use Serena, CodeGraph, or another graph tool only when", plan_prompt.body)
        self.assertNotIn("use CodeGraphContext (`cgc`) for repo-wide ownership", plan_prompt.body)
        self.assertNotIn("Do not use the legacy `codegraph` CLI or `.codegraph/` indexes in envctl", plan_prompt.body)
        self.assertIn("envctl --headless --plan <selector>", plan_prompt.body)
        self.assertIn("Ground the follow-up in the real supported flow", plan_prompt.body)
        self.assertIn("Use these repo-scoped command forms as the source of examples", plan_prompt.body)
        self.assertIn("Multi-launch choices mean separate commands", plan_prompt.body)
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
        self.assertIn("plan-agent scope metadata and dependency-prep intent", plan_prompt.body)
        self.assertIn('Separately record the validation lane: `envctl test-focused --ship-on-pass "<message>"` by default', plan_prompt.body)
        self.assertIn("including staging via git add, commit, push, PR/check reporting", plan_prompt.body)
        self.assertIn("Do not record or recommend standalone `envctl test-focused`", plan_prompt.body)
        self.assertIn('they do not replace `envctl test-focused --ship-on-pass "<message>"`', plan_prompt.body)
        self.assertIn("they never justify standalone `envctl test-focused`", plan_prompt.body)
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
                self.assertIn("pass it inline with `envctl test-focused --ship-on-pass", prompt.body)
                self.assertIn("Do not run standalone `envctl test-focused` first or repeat it afterward", prompt.body)
                self.assertIn("including staging intended changes via git add", prompt.body)
                self.assertIn("envctl ship -m", prompt.body)
                self.assertIn("Do not run `envctl commit` separately", prompt.body)
                self.assertIn("full cumulative set of changes between commits", prompt.body)
