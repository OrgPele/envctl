# Envctl Review Optional Origin-Tab Launch

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Extend interactive dashboard `review` so, after a successful review run, envctl can optionally open an AI tab for origin-side worktree review instead of stopping at markdown diff-bundle generation.
  - Reuse the existing origin-side review prompt contract in [`python/envctl_engine/runtime/prompt_templates/review_worktree_imp.md`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/runtime/prompt_templates/review_worktree_imp.md), rather than inventing a second review prompt or duplicating review instructions inline.
  - Reuse or extract the existing `cmux` launch transport from [`python/envctl_engine/planning/plan_agent_launch_support.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py) so review-tab launch and plan-agent launch do not drift into two separate shell-automation stacks.
  - Preserve all existing `review` behavior for headless/direct CLI usage and for the current diff-bundle output.
- Non-goals:
  - Changing the existing review bundle generation in [`python/envctl_engine/actions/project_action_domain.py:192`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/project_action_domain.py#L192).
  - Prompting during direct `envctl review ...`, `python -m envctl_engine.actions.actions_cli review`, or any non-dashboard batch/headless review flow.
  - Replacing the existing manual `review_worktree_imp` preset workflow outside envctl.
  - Designing a generic “open arbitrary AI tabs for any action” system in the first slice.
  - Supporting multi-target or `Main` review-tab launch in the first slice.
- Assumptions:
  - The user’s truncated “open a new tab ... where” request is resolved as: open an origin-side AI review tab that starts in the current repo root and invokes the existing `review_worktree_imp` preset against the selected worktree. Repo evidence supports this because:
    - the preset already exists and is explicitly origin-side and read-only ([`python/envctl_engine/runtime/prompt_templates/review_worktree_imp.md`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/runtime/prompt_templates/review_worktree_imp.md));
    - prior planning/changelog evidence explicitly said automatic origin-side review launch was deferred, not rejected ([`todo/plans/features/envctl-prompt-overwrite-confirmation-and-origin-review-preset.md:172`](/Users/kfiramar/projects/current/envctl/todo/plans/features/envctl-prompt-overwrite-confirmation-and-origin-review-preset.md#L172), [`docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md:156`](/Users/kfiramar/projects/current/envctl/docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md#L156)).
  - First implementation should offer the extra tab only when dashboard review resolves to exactly one non-`Main` worktree target, because `review_worktree_imp` is a single-worktree prompt contract and the user phrased the request in the singular.

## Goal (user experience)
When an operator runs `review` from the interactive dashboard against a single implementation worktree and the review action succeeds, envctl should ask a simple yes/no question about opening an origin-side AI review tab. If the operator says yes, envctl should open one new `cmux` surface, keep it interactive, `cd` into the current local/origin repo root, launch the configured AI CLI, and invoke `review_worktree_imp` with the selected worktree as the explicit target override. If the operator says no, envctl should keep the current behavior: the review bundle is generated and printed, and nothing else changes. Direct CLI review, headless review, `Main` review, and multi-target review should keep their current behavior in this first iteration.

## Business logic and data model mapping
- Review command routing and action execution:
  - [`python/envctl_engine/runtime/command_router.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/runtime/command_router.py)
  - [`python/envctl_engine/runtime/engine_runtime.py:_run_analyze_action`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/runtime/engine_runtime.py#L1061)
  - [`python/envctl_engine/actions/action_command_orchestrator.py:run_review_action`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L458)
  - [`python/envctl_engine/actions/action_command_orchestrator.py:run_project_action`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L723)
- Current review domain behavior and review bundle generation:
  - [`python/envctl_engine/actions/project_action_domain.py:run_review_action`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/project_action_domain.py#L192)
  - [`python/envctl_engine/actions/project_action_domain.py:_run_analyze_helper`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/project_action_domain.py#L903)
  - [`python/envctl_engine/actions/project_action_domain.py:_tree_diffs_root`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/project_action_domain.py#L1000)
  - [`python/envctl_engine/actions/project_action_domain.py:_tree_diffs_output_path`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/project_action_domain.py#L1011)
  - [`python/envctl_engine/actions/project_action_domain.py:_print_review_completion`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/project_action_domain.py#L1061)
- Dashboard interactive review ownership and the obvious hook point:
  - [`python/envctl_engine/ui/dashboard/orchestrator.py:_run_interactive_command`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L93)
  - [`python/envctl_engine/ui/dashboard/orchestrator.py:_apply_interactive_target_selection`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L330)
  - [`python/envctl_engine/ui/dashboard/orchestrator.py:_apply_project_target_selection`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L446)
  - [`python/envctl_engine/ui/dashboard/orchestrator.py:_project_roots_for_route`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L712)
  - [`python/envctl_engine/ui/dashboard/orchestrator.py:_prompt_yes_no_dialog`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L763)
- Existing `cmux` launch transport that should be reused/extracted rather than duplicated:
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:launch_plan_agent_terminals`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L296)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:_run_surface_bootstrap`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L474)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:_launch_cli_bootstrap_commands`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L808)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:_slash_command`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L1389)
  - [`python/envctl_engine/planning/plan_agent_launch_support.py:_ensure_workspace_id`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L839)
- Existing plan-agent config/env keys that likely become the review launcher’s transport defaults:
  - [`python/envctl_engine/config/__init__.py:_build_defaults`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/config/__init__.py#L31)
  - [`python/envctl_engine/config/__init__.py:EngineConfig`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/config/__init__.py#L263)
  - [`docs/reference/configuration.md`](/Users/kfiramar/projects/current/envctl/docs/reference/configuration.md)
- Existing origin-side review preset and prompt installation/docs:
  - [`python/envctl_engine/runtime/prompt_templates/review_worktree_imp.md`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/runtime/prompt_templates/review_worktree_imp.md)
  - [`python/envctl_engine/runtime/prompt_install_support.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/runtime/prompt_install_support.py)
  - [`docs/user/ai-playbooks.md`](/Users/kfiramar/projects/current/envctl/docs/user/ai-playbooks.md)
  - [`docs/reference/commands.md`](/Users/kfiramar/projects/current/envctl/docs/reference/commands.md)
- Existing tests that lock the current review and plan-launch behavior:
  - [`tests/python/ui/test_dashboard_orchestrator_restart_selector.py`](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_dashboard_orchestrator_restart_selector.py)
  - [`tests/python/actions/test_actions_cli.py`](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_cli.py)
  - [`tests/python/actions/test_actions_parity.py`](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_parity.py)
  - [`tests/python/planning/test_plan_agent_launch_support.py`](/Users/kfiramar/projects/current/envctl/tests/python/planning/test_plan_agent_launch_support.py)
  - [`tests/python/runtime/test_engine_runtime_real_startup.py`](/Users/kfiramar/projects/current/envctl/tests/python/runtime/test_engine_runtime_real_startup.py)
  - [`tests/python/runtime/test_prereq_policy.py`](/Users/kfiramar/projects/current/envctl/tests/python/runtime/test_prereq_policy.py)

## Current behavior (verified in code)
- Interactive dashboard review is only a normal action dispatch today.
  - [`DashboardOrchestrator._run_interactive_command(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L93) parses the dashboard command, applies target selection, and then directly calls `runtime.dispatch(route)`.
  - Only `pr` currently gets extra pre/post dashboard-owned orchestration via `_maybe_prepare_pr_commit(...)`; `review` has no equivalent preflight or post-success hook.
- Dashboard `review` target selection is project-only and can select more than one project.
  - [`_dashboard_owned_project_selection_commands()`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L441) includes `review`.
  - [`_apply_project_target_selection(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L446) allows multi-select and `allow_all=True`.
- The review action itself only writes review artifacts and prints completion details.
  - [`run_review_action(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/project_action_domain.py#L192) either:
    - invokes the repo helper `utils/analyze-tree-changes.sh` through `_run_analyze_helper(...)`, or
    - writes markdown directly with diff/stat/status data under `_tree_diffs_root()/review/...`.
  - No code in the review domain launches `cmux`, opens tabs, starts Codex/OpenCode, or dispatches prompts.
- The only shipped `cmux` AI-tab automation lives under plan-agent support and is hard-wired to planning semantics.
  - [`launch_plan_agent_terminals(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L296) activates only for `route.command == "plan"` and not `planning_prs`.
  - The bootstrap path assumes worktree launch semantics: `cd <worktree>`, start configured CLI, then submit the configured preset.
  - Event names are planning-specific (`planning.agent_launch.*`), and the default workspace logic is also plan-specific (`"<current workspace> implementation"` when no explicit override exists).
- The repo already has the exact manual prompt contract the requested tab would need.
  - [`review_worktree_imp.md`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/runtime/prompt_templates/review_worktree_imp.md) explicitly says the current repo is the unedited baseline and `$ARGUMENTS` can override the target worktree path or name.
  - [`docs/user/ai-playbooks.md`](/Users/kfiramar/projects/current/envctl/docs/user/ai-playbooks.md) and [`docs/reference/commands.md`](/Users/kfiramar/projects/current/envctl/docs/reference/commands.md) document this preset as a manual origin-side follow-up.
- Prior project evidence explicitly left automatic origin-side review launch for later.
  - [`docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md:156`](/Users/kfiramar/projects/current/envctl/docs/changelog/features_envctl_prompt_overwrite_confirmation_and_origin_review_preset-1_changelog.md#L156) says the preset is intentionally manual and automatic origin-side review launch is out of scope.
- CLI prereq and inspection surfaces are currently startup/plan-centric, not review-tab-centric.
  - [`python/envctl_engine/runtime/cli.py:check_prereqs`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/runtime/cli.py#L35) only adds `cmux`/AI CLI prereqs for `plan`.
  - [`python/envctl_engine/runtime/inspection_support.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/runtime/inspection_support.py) exposes `plan_agent` state in `show-config`/`explain-startup`; there is no parallel review-launch inspection surface today.

## Root cause(s) / gaps
- There is no review-specific orchestration point after a successful dashboard review dispatch.
  - The dashboard loop has no “post-success optional next action” hook for `review`, so current behavior ends after action execution and normal state refresh.
- The current `cmux` launcher is too plan-specific to reuse as-is.
  - It assumes a created worktree cwd, a plan preset, plan-specific workspace defaults, and planning-specific event names.
  - Review launch needs a different cwd (`repo_root`), different default workspace policy (current or explicitly configured workspace, not sibling implementation workspace), and a prompt string that includes a worktree override.
- There is no helper for slash-command composition with explicit prompt arguments.
  - [`_slash_command(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py#L1389) only formats the preset name; it does not compose `/prompts:review_worktree_imp <worktree>` or the OpenCode equivalent.
- The origin-side review preset is single-worktree oriented, while interactive dashboard `review` can target multiple projects.
  - Without a deliberate narrowing rule, accepting the prompt could unexpectedly open several tabs or produce ambiguous target selection.
- Current success metadata for review actions does not persist any structured “launch this next” context.
  - [`_persist_project_action_result(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/actions/action_command_orchestrator.py#L982) stores failed action summaries/reports only; successful review runs do not save a summary path or launch hint into run state.

## Plan
### 1) Define a narrow v1 product contract around dashboard-interactive review only
- Scope the new behavior to the dashboard interactive path owned by [`DashboardOrchestrator._run_interactive_command(...)`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py#L93).
- Trigger the extra prompt only when all of these are true:
  - `route.command == "review"`
  - the review action returned success
  - the selected review scope resolves to exactly one git-root-distinct target
  - that target is a worktree target, not `Main` / repo-root review
  - launch prerequisites are actually satisfiable (`cmux` context/workspace + configured CLI executable + shell executable)
- Preserve current behavior with no extra prompt for:
  - direct CLI `review`
  - headless/batch review
  - failed review runs
  - `Main` review
  - multi-target review
- Keep the existing review bundle generation as the primary action. The new tab is an optional follow-up after success, not a replacement for the current markdown output.

### 2) Extract the `cmux` transport into a reusable launcher contract
- Refactor [`python/envctl_engine/planning/plan_agent_launch_support.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/planning/plan_agent_launch_support.py) so the raw `cmux` surface creation, CLI bootstrap, readiness waits, and prompt submission are shared helpers rather than being owned only by the `plan` command entrypoint.
- Recommended structure:
  - keep plan-specific selection/result types (`CreatedPlanWorktree`, `PlanSelectionResult`) where they are
  - introduce a generic launch request/result layer for:
    - workspace policy
    - tab title
    - cwd to `cd` into
    - CLI/preset/prompt text
    - event namespace or event kind
- Preserve plan behavior exactly by making `launch_plan_agent_terminals(...)` an adapter over the shared transport rather than rewriting its product logic.
- Keep the review launch transport in the same module or a nearby shared launcher module, not in the review domain file, so `project_action_domain.py` remains review-output-only.

### 3) Add an origin-review launch helper that is explicit about repo root, target worktree, and workspace policy
- Add a dedicated helper, for example `launch_review_agent_terminal(...)`, that:
  - receives `repo_root`, `project_name`, and `project_root`
  - `cd`s into `repo_root`, not the target worktree
  - starts the configured AI CLI
  - submits the origin-side review prompt with an explicit worktree override
- Recommended prompt-text contract:
  - Codex: `/prompts:review_worktree_imp <worktree-path-or-name>`
  - OpenCode: `/review_worktree_imp <worktree-path-or-name>`
- Prefer passing the explicit worktree name/path every time instead of relying on the prompt’s “current plan file” fallback. The dashboard review flow already knows the selected target, so the launch should be deterministic.
- Reuse current transport config defaults where it is safe:
  - CLI: `ENVCTL_PLAN_AGENT_CLI`
  - CLI command override: `ENVCTL_PLAN_AGENT_CLI_CMD`
  - shell: `ENVCTL_PLAN_AGENT_SHELL`
  - explicit workspace override: `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE`
  - strict context rule: `ENVCTL_PLAN_AGENT_REQUIRE_CMUX_CONTEXT`
- Do not require `ENVCTL_PLAN_AGENT_TERMINALS_ENABLE` for the review flow in v1.
  - The opt-in is the yes/no prompt itself.
  - Review should not silently inherit “always launch tabs” from plan-agent enablement because the user asked for an explicit interactive yes/no choice.
- Default workspace policy should differ from plan:
  - if `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` is set, honor it
  - otherwise target the current workspace rather than deriving `"<current workspace> implementation"`
  - this keeps the origin-side review tab aligned with the current repo CLI context

### 4) Add a dashboard post-success review-tab offer instead of a pre-dispatch prompt
- Add a new helper in [`python/envctl_engine/ui/dashboard/orchestrator.py`](/Users/kfiramar/projects/current/envctl/python/envctl_engine/ui/dashboard/orchestrator.py), for example `_maybe_offer_review_tab_launch(...)`, and call it inside `_run_interactive_command(...)` only after:
  - `runtime.dispatch(route)` succeeds, and
  - the command is `review`
- The helper should:
  - resolve the selected project root via `_project_roots_for_route(...)`
  - dedupe by git root the same way PR flow already avoids duplicate worktree handling
  - reject `Main` / repo-root review
  - evaluate launch readiness before asking the question
  - prompt with a simple yes/no surface using `_prompt_yes_no_dialog(...)`
  - launch asynchronously on accept
- Asking after success keeps the UX aligned with the request:
  - review still creates the diff file/bundle first
  - the operator then chooses whether to escalate into a live review tab
  - failures do not create an extra prompt or half-launched AI surface

### 5) Keep target eligibility intentionally narrow and deterministic
- V1 should only offer the review tab when there is one eligible worktree target.
- For multi-target review:
  - keep the current review bundle behavior only
  - emit a bounded skip reason such as `multiple_review_targets`
  - do not ask a yes/no question that could unexpectedly open many tabs
- For `Main` review:
  - keep the current review bundle behavior only
  - skip the prompt because `review_worktree_imp` is specifically an origin-vs-worktree contract
- For duplicate targets that collapse to the same git root:
  - dedupe first
  - if the result is one distinct worktree, the prompt may still appear

### 6) Add bounded observability and keep state persistence minimal
- Add dashboard/review launch events such as:
  - `dashboard.review_tab.evaluate`
  - `dashboard.review_tab.skipped`
  - `dashboard.review_tab.prompt`
  - `dashboard.review_tab.accepted`
  - `dashboard.review_tab.declined`
  - `dashboard.review_tab.launched`
  - `dashboard.review_tab.failed`
- Event payloads should include only bounded metadata:
  - project/worktree name
  - whether the target was `Main`
  - whether launch prereqs were satisfied
  - skip/failure reason
  - CLI selected
- Do not persist `cmux` surface IDs or shell commands into run state.
- No data migration or backfill is needed. This feature is ephemeral UI/session behavior only.

### 7) Update docs around the now-automated path and its boundaries
- Update [`docs/user/ai-playbooks.md`](/Users/kfiramar/projects/current/envctl/docs/user/ai-playbooks.md) to distinguish:
  - manual `review_worktree_imp` usage from the local/origin repo CLI
  - the new optional dashboard review-tab launch path
- Update [`docs/reference/commands.md`](/Users/kfiramar/projects/current/envctl/docs/reference/commands.md) to document:
  - dashboard `review` can optionally offer an origin-side AI tab after success
  - this is single-worktree-only in the first version
  - it reuses the existing review prompt preset instead of changing review bundle generation
- Update [`docs/reference/configuration.md`](/Users/kfiramar/projects/current/envctl/docs/reference/configuration.md) only if implementation explicitly reuses the plan-agent transport keys for review launch and that coupling needs to be user-visible.
- Do not expand `show-config`/`explain-startup` in v1 unless a new review-specific config switch is added. Current inspection surfaces are startup-centric, and this feature is prompt-driven rather than startup-driven.

## Tests (add these)
### Backend tests
- Extend [`tests/python/planning/test_plan_agent_launch_support.py`](/Users/kfiramar/projects/current/envctl/tests/python/planning/test_plan_agent_launch_support.py):
  - generic/shared launcher path still preserves current plan-agent command ordering
  - new review-launch request types `cd` into `repo_root`, not `project_root`
  - review prompt text composes the CLI-specific slash command plus explicit worktree argument
  - current-workspace default is used for review launch when no explicit workspace override is set
  - explicit `ENVCTL_PLAN_AGENT_CMUX_WORKSPACE` still overrides the default workspace for review launch
- Extend [`tests/python/actions/test_actions_parity.py`](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_parity.py):
  - direct/headless `review` behavior remains unchanged and prompt-free
  - no review-tab launch helper is invoked when `review` is dispatched outside dashboard-interactive mode

### Frontend tests
- Extend [`tests/python/ui/test_dashboard_orchestrator_restart_selector.py`](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_dashboard_orchestrator_restart_selector.py):
  - successful single-worktree review prompts for the optional tab
  - accepting the prompt launches the review tab after review dispatch succeeds
  - declining the prompt leaves review at current behavior
  - failed review does not prompt or launch
  - `Main` review does not prompt
  - multi-target review does not prompt
  - typed dashboard review command with explicit `--project` still triggers the post-success offer when the scope is eligible
  - duplicate project selections that collapse to one git root still prompt only once
- If the launcher call is exposed on the runtime stub rather than patched as a module-level helper, update the stub and assertions accordingly.

### Integration/E2E tests
- Extend [`tests/python/runtime/test_engine_runtime_real_startup.py`](/Users/kfiramar/projects/current/envctl/tests/python/runtime/test_engine_runtime_real_startup.py) only if the plan-agent transport extraction changes startup behavior or shared launcher wiring:
  - existing plan-agent launch semantics still trigger only for newly created plan worktrees
  - no regression in plan startup when the shared launcher module is reused by review
- No new end-to-end suite is required for direct CLI review because the requested feature is intentionally dashboard-interactive only.
- Add a short manual verification checklist:
  - dashboard `review` on one worktree -> review bundle still prints -> yes opens origin-side AI tab
  - dashboard `review` on one worktree -> no keeps current behavior
  - dashboard `review` on `Main` -> no prompt
  - dashboard `review` on multi-select -> no prompt
  - verify the opened tab starts in repo root and receives `review_worktree_imp <target>`

## Observability / logging (if relevant)
- Keep review-tab telemetry separate from `planning.agent_launch.*` so plan-launch and review-launch diagnostics do not blur together.
- Print one bounded summary line on successful launch, for example:
  - `Opened origin review tab for feature-a-1.`
- Print bounded skip messages only when they materially explain why the prompt did not appear in an otherwise eligible-looking dashboard flow.
- Avoid logging raw `cmux` command arrays or the full prompt body unless debug mode later requires that as a separate feature.

## Rollout / verification
- Implement in this order:
  1. extract/reuse the shared `cmux` launcher substrate without changing plan behavior
  2. add the review-launch helper with explicit repo-root/worktree prompt composition
  3. wire the post-success dashboard hook for interactive review
  4. add docs and regression coverage
- Verification commands:
  - `./.venv/bin/python -m pytest -q tests/python/ui/test_dashboard_orchestrator_restart_selector.py`
  - `./.venv/bin/python -m pytest -q tests/python/planning/test_plan_agent_launch_support.py`
  - `./.venv/bin/python -m pytest -q tests/python/actions/test_actions_parity.py tests/python/actions/test_actions_cli.py`
  - if the shared launcher refactor touches startup wiring: `./.venv/bin/python -m pytest -q tests/python/runtime/test_engine_runtime_real_startup.py tests/python/runtime/test_prereq_policy.py`
- Manual verification:
  - run dashboard review inside `cmux` against a single worktree with installed prompts and confirm the tab opens only after review success
  - inspect the opened surface and confirm the shell starts in repo root, not the worktree
  - confirm Codex/OpenCode receive the review preset with the explicit worktree override text

## Definition of done
- Interactive dashboard `review` still generates the current review bundle and now optionally offers an origin-side AI review tab when the selected target is exactly one non-`Main` worktree.
- Accepting the prompt opens one `cmux` surface, launches the configured AI CLI, and invokes `review_worktree_imp` against the selected worktree from the repo root.
- Declining or ineligible cases preserve current behavior with no tab launch.
- Direct CLI/headless review remains unchanged.
- Shared launch-transport refactoring does not regress existing plan-agent launch behavior.
- Targeted dashboard, launcher, and review-regression tests cover the new flow and its skip boundaries.

## Risk register (trade-offs or missing tests)
- Risk: slash-command-plus-arguments behavior for `review_worktree_imp <worktree>` is inferred from the prompt `$ARGUMENTS` contract, but the repo does not currently have automated evidence of prompt invocation with trailing args.
  - Mitigation: add focused launcher unit coverage for prompt text composition and require manual `cmux` verification for Codex/OpenCode prompt execution.
- Risk: extracting shared `cmux` transport from the existing plan-agent launcher can regress `plan` if the refactor is too invasive.
  - Mitigation: preserve `launch_plan_agent_terminals(...)` as an adapter over the shared layer and keep plan-launch regression coverage in place.
- Risk: reusing plan-agent transport config without a review-specific config namespace may make the coupling non-obvious to operators.
  - Mitigation: document clearly that review-tab launch reuses the same CLI/shell/workspace transport settings, while the review prompt itself remains an explicit yes/no choice.
- Risk: operators may expect multi-target review to open one tab per target.
  - Mitigation: make the first-version single-target boundary explicit in prompt copy/docs and keep multi-target review on the existing bundle-only path.

## Open questions (only if unavoidable)
- None. The implementation can proceed from current repo evidence with the assumptions above.
