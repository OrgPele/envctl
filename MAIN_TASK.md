# Envctl PR Dirty-Worktree Commit Confirmation Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Before interactive dashboard PR creation, detect staged/unstaged dirty worktrees for the selected target scope and ask whether the operator wants to commit first.
  - Reuse the existing commit action when the operator accepts, rather than duplicating git mutation logic inside the PR flow.
  - Preserve current PR creation behavior when the operator declines or when the selected target scope is already clean.
  - Keep batch/headless PR execution deterministic and non-interactive.
- Non-goals:
  - Changing direct non-dashboard `envctl pr` or `python -m envctl_engine.actions.actions_cli pr` to auto-prompt or auto-commit in this first change.
  - Redesigning PR title/body generation, review-base logic, or the underlying `utils/create-pr.sh` / `gh pr create` behavior.
  - Changing commit semantics away from the current `git add -A` + `git commit` + `git push` flow.
- Assumptions:
  - Dirty detection should be evaluated per selected target git root using the same repository resolution contract as existing actions (`python/envctl_engine/actions/project_action_domain.py:resolve_git_root`).
  - Untracked files should count as dirty for this prompt because the current commit action stages them via `git add -A`.
  - If the operator declines the prompt, envctl should continue with normal PR creation from the current committed branch state to preserve current behavior.
  - If the commit step fails for any selected dirty target, envctl should stop before PR creation rather than creating a partial subset of PRs.

## Goal (user experience)
When the operator triggers `pr` from the interactive dashboard and the selected target worktree has staged, unstaged, or untracked changes, envctl should pause before PR creation and ask whether to commit those changes first. Choosing Yes should reuse the existing commit flow, including the current commit-message prompt/default behavior, then continue into PR creation. Choosing No should continue with the current PR flow without committing. Clean targets and non-interactive PR commands should behave exactly as they do today.

## Business logic and data model mapping
- Dashboard interactive command routing and prompt ownership:
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_run_interactive_command`
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_apply_interactive_target_selection`
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_apply_pr_selection`
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_apply_commit_selection`
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_prompt_commit_message`
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_read_interactive_line`
- PR/commit action dispatch and env bridging:
  - `python/envctl_engine/actions/action_command_orchestrator.py:run_pr_action`
  - `python/envctl_engine/actions/action_command_orchestrator.py:run_commit_action`
  - `python/envctl_engine/actions/action_command_orchestrator.py:run_project_action`
  - `python/envctl_engine/actions/action_command_support.py:build_action_extra_env`
  - `python/envctl_engine/actions/action_command_support.py:build_action_env`
- Git domain behavior:
  - `python/envctl_engine/actions/project_action_domain.py:run_pr_action`
  - `python/envctl_engine/actions/project_action_domain.py:run_commit_action`
  - `python/envctl_engine/actions/project_action_domain.py:resolve_git_root`
  - `python/envctl_engine/actions/project_action_domain.py:_run_git`
  - `python/envctl_engine/actions/project_action_domain.py:_git_output`
- Existing prompt surfaces and fallback primitives:
  - `python/envctl_engine/ui/textual/screens/text_input_dialog.py:run_text_input_dialog_textual`
  - `python/envctl_engine/runtime/engine_runtime.py:_prompt_yes_no`
  - `python/envctl_engine/runtime/lifecycle_cleanup_orchestrator.py:prompt_yes_no`
- Existing persisted action results that must remain aligned:
  - `python/envctl_engine/actions/action_command_orchestrator.py:_persist_project_action_result`
  - `python/envctl_engine/state/models.py:RunState.metadata["project_action_reports"]`

## Current behavior (verified in code)
- Dashboard `p` goes through dashboard-owned PR selection and then dispatches a normal `pr` route:
  - `DashboardOrchestrator._run_interactive_command(...)` parses the command, forces `batch=True` plus `interactive_command=True`, applies interactive target selection, and finally calls `runtime.dispatch(route)`.
  - `DashboardOrchestrator._apply_pr_selection(...)` selects project scope, base branch, and optional PR body, but does not inspect worktree dirtiness or branch into commit behavior.
- Dashboard `c` already has pre-dispatch message prompting, but `pr` does not:
  - `_apply_commit_selection(...)` prompts for `commit_message` when the route does not already carry one.
  - `_apply_pr_selection(...)` prompts for `pr_body`, but there is no adjacent commit decision.
- PR and commit are separate action routes all the way down:
  - `ActionCommandOrchestrator.run_pr_action(...)` and `run_commit_action(...)` both delegate to `run_project_action(...)` with different `command_name` / env keys.
  - `build_action_extra_env(...)` forwards `pr_base`, `pr_body`, `commit_message`, and `commit_message_file`, but nothing about a pre-PR commit consent flow.
- The domain PR action does not look at working tree status:
  - `project_action_domain.run_pr_action(...)` checks git availability, detached HEAD, base branch, and existing PR, then runs `utils/create-pr.sh` or `gh pr create`.
  - There is no `git status` preflight in `run_pr_action(...)`.
- The domain commit action stages everything and pushes:
  - `project_action_domain.run_commit_action(...)` runs `git add -A`, `git status --porcelain`, resolves the commit message, commits, and pushes with `git push -u`.
- There is no reusable dashboard confirmation dialog today:
  - Dashboard text entry uses `run_text_input_dialog_textual(...)`.
  - Generic yes/no prompting exists only as a simple `input()` helper in cleanup orchestration (`LifecycleCleanupOrchestrator.prompt_yes_no(...)`), and dashboard PR/commit tests do not cover a confirmation modal.
- Existing test evidence locks in the current split:
  - `tests/python/actions/test_actions_cli.py` verifies PR creation, detached-HEAD skip, existing-PR skip, and commit staging/push behavior.
  - `tests/python/ui/test_dashboard_orchestrator_restart_selector.py` verifies PR target/base/message prompting and separate commit-message prompting, but has no dirty-worktree preflight coverage.
  - `tests/python/actions/test_actions_cli.py:test_pr_action_interactive_mode_does_not_prompt_for_base_branch` also confirms the domain action path avoids direct `input()` prompting even when `ENVCTL_ACTION_INTERACTIVE=1`.

## Root cause(s) / gaps
- There is no read-only dirty-worktree classification helper that the dashboard PR flow can call before dispatching the real PR action.
- The dashboard PR flow already owns interactive prompts, but it stops at project/base/body selection and never decides whether to branch into a commit-first step.
- The only existing yes/no prompt primitive is a basic stdin helper outside the dashboard UI stack, so there is no first-class confirmation surface for this decision.
- Commit and PR are intentionally independent actions; without an orchestrated preflight, the PR flow cannot reuse commit behavior before dispatch.
- The current tests validate PR and commit as separate flows, so there is no regression coverage for the requested behavior: dirty selected target(s) plus interactive dashboard PR creation.

## Plan
### 1) Define the contract narrowly around interactive dashboard PR creation
- Limit the first implementation to dashboard-owned interactive PR creation triggered through `DashboardOrchestrator`.
- Preserve current behavior for:
  - clean targets
  - operator declining the prompt
  - operator running non-interactive / batch / headless PR commands
  - direct CLI/domain PR execution outside the dashboard
- Document explicitly that the prompt is about committing the currently dirty selected target scope before PR creation, not about changing the eventual PR payload generation rules.

### 2) Add a reusable, read-only dirty-worktree probe
- Add a helper under `python/envctl_engine/actions/` or `python/envctl_engine/ui/dashboard/` that:
  - resolves the target git root with `resolve_git_root(project_root, repo_root)`
  - runs `git status --porcelain --untracked-files=all`
  - classifies staged, unstaged, and untracked dirtiness
  - returns a structured summary per selected target or deduplicated git root
- Keep the helper read-only and bounded:
  - no staging
  - no commit attempts
  - no raw porcelain output printed to the user
- Deduplicate repeated git roots so the same worktree is not probed or prompted more than once.

### 3) Insert a PR preflight hook after route scoping but before dispatch
- Add a dedicated helper in `DashboardOrchestrator`, for example `_maybe_prepare_pr_commit(...)`, and call it from `_run_interactive_command(...)` after `_apply_interactive_target_selection(...)` has finalized the PR route.
- This placement ensures the preflight sees the actual selected PR scope for both:
  - the `p` alias flow
  - typed dashboard commands like `pr --project foo --pr-base main`
- The preflight helper should:
  - resolve the selected project targets from the finalized route
  - run dirty-state detection for those targets
  - skip immediately if all are clean
  - prompt once when any selected target is dirty

### 4) Add a dashboard confirmation surface with clear fallback behavior
- Prefer a reusable dashboard confirmation helper rather than embedding raw `input()` directly into PR routing code.
- Recommended shape:
  - `DashboardOrchestrator._prompt_yes_no_dialog(...)`
  - optional new shared UI helper such as `python/envctl_engine/ui/textual/screens/confirm_dialog.py`
- Fallback order should be explicit:
  1. a runtime-provided confirm hook if one is added
  2. a Textual confirm dialog when available
  3. runtime `_prompt_yes_no(...)` or `_read_interactive_line(...)` fallback for basic TTY operation
- Treat the result as tri-state:
  - accept: run commit first
  - decline: continue PR without commit
  - cancel/escape: abort the PR command and return to the dashboard without dispatching either action

### 5) Reuse the existing commit route instead of duplicating git mutation logic
- When the operator accepts, synthesize and dispatch a `commit` route rather than calling `git add` / `git commit` directly from the PR preflight.
- Reuse existing commit semantics:
  - current target scoping
  - existing commit message prompt/default logic via `_apply_commit_selection(...)`
  - existing action env propagation and domain execution
- Recommended execution sequence:
  1. finalize the PR route
  2. detect dirty selected targets
  3. prompt accept / decline / cancel
  4. if accept, build a commit route scoped to the dirty subset
  5. dispatch commit and reload latest state
  6. only if commit succeeded, dispatch the original PR route
- Do not add a second git mutation implementation in the dashboard layer.

### 6) Keep multi-target behavior safe and deterministic
- Dirty detection should be per selected target or git root so the prompt can report whether one or many selected targets are dirty.
- For multi-target PR flows:
  - commit only the dirty subset
  - stop the PR phase if any commit target fails
  - do not proceed with PR creation for a clean subset while another selected target had a commit failure
- Preserve current `project_action_reports` semantics for commit and PR actions; the preflight itself should not invent a new persisted action result type unless implementation evidence proves it is needed.

### 7) Keep non-interactive and direct CLI behavior unchanged in the first iteration
- Do not add implicit commit-before-PR behavior to:
  - `envctl pr --headless`
  - `envctl pr --batch`
  - `python -m envctl_engine.actions.actions_cli pr`
- Keep `project_action_domain.run_pr_action(...)` prompt-free so existing direct-action tests that guard against unexpected prompting remain valid.
- If the product later wants a generic CLI prompt or an auto-accept flag, treat that as follow-on work rather than widening this first change.

### 8) Add bounded diagnostics and documentation updates
- Emit dashboard-level events for:
  - dirty state detected / not detected
  - prompt shown
  - operator accepted / declined / cancelled
  - commit-before-PR started / failed / completed
- Suggested event names:
  - `dashboard.pr_dirty_state`
  - `dashboard.pr_dirty_commit.prompt`
  - `dashboard.pr_dirty_commit.accepted`
  - `dashboard.pr_dirty_commit.declined`
  - `dashboard.pr_dirty_commit.cancelled`
  - `dashboard.pr_dirty_commit.failed`
- Keep event payloads bounded to counts and coarse dirtiness categories, not raw `git status` output.
- Update docs/changelog to clarify that dashboard `pr` may now offer a commit-first prompt when selected targets are dirty, and that declining preserves previous PR behavior.

## Tests (add these)
### Backend tests
- Extend [tests/python/actions/test_actions_cli.py](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_cli.py):
  - add coverage for the dirty-state classification helper: clean, staged-only, unstaged-only, untracked-only, mixed
  - keep a regression proving `run_pr_action(...)` itself still does not prompt or auto-commit in the domain/CLI path
- Extend [tests/python/actions/test_actions_parity.py](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_parity.py):
  - add a parity regression proving batch/headless PR behavior remains prompt-free
  - add a regression that the commit-before-PR dashboard flow still preserves existing `ENVCTL_ACTION_INTERACTIVE` semantics for the commit step when routed through the action executor

### Frontend tests
- Extend [tests/python/ui/test_dashboard_orchestrator_restart_selector.py](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_dashboard_orchestrator_restart_selector.py):
  - dirty selected target plus Yes dispatches commit first, then PR
  - dirty selected target plus No skips commit and dispatches PR only
  - dirty selected target plus cancel aborts without dispatching commit or PR
  - clean selected target does not prompt
  - explicit typed dashboard PR routes still go through the dirty preflight
  - commit failure aborts PR dispatch
  - multi-target selection commits only dirty targets and stops PR if any commit fails
- If a new confirm dialog is added, add `tests/python/ui/test_confirm_dialog.py` or extend [tests/python/ui/test_text_input_dialog.py](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_text_input_dialog.py) with button/key-path coverage for accept / decline / cancel behavior.

### Integration/E2E tests
- Prefer one focused integration extension in [tests/python/actions/test_actions_parity.py](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_parity.py) only if unit-level dashboard tests are not sufficient to prove the full sequence:
  - dirty working tree detected
  - operator accepts commit
  - commit route runs before PR route
  - PR route still emits the existing success/status behavior afterward
- No broader end-to-end suite is required unless the new confirmation UI introduces backend- or TTY-specific regressions that targeted dashboard tests cannot reproduce.

## Observability / logging (if relevant)
- Keep new diagnostics at the dashboard/orchestration layer, not inside the domain PR action.
- Record only bounded summary data:
  - selected project count
  - dirty project count
  - dirtiness category presence (`staged`, `unstaged`, `untracked`)
  - operator choice
  - follow-on commit outcome
- Do not emit raw `git status --porcelain` output into standard runtime events.
- If a new confirmation dialog is added, emit fallback-reason diagnostics in the same style used elsewhere when Textual is unavailable.

## Rollout / verification
- Implement in this order:
  1. read-only dirty-state probe and backend tests
  2. dashboard confirmation helper and fallback behavior
  3. PR preflight orchestration with commit-route reuse
  4. docs/changelog updates
- Verification commands:
  - `PYTHONPATH=python python3 -m unittest tests.python.actions.test_actions_cli`
  - `PYTHONPATH=python python3 -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector`
  - `PYTHONPATH=python python3 -m unittest tests.python.actions.test_actions_parity`
  - if a new dialog helper is added: `PYTHONPATH=python python3 -m unittest tests.python.ui.test_text_input_dialog tests.python.ui.test_confirm_dialog`
- Manual verification:
  - from the interactive dashboard, trigger `pr` on a target with only unstaged changes and confirm the prompt appears
  - choose Yes and verify commit runs before PR creation
  - choose No and verify PR creation proceeds without a new commit
  - choose Cancel and verify no commit or PR is run
  - repeat on a clean target and confirm no extra prompt appears
  - verify headless/batch `pr` behavior remains unchanged

## Definition of done
- Interactive dashboard PR creation detects dirty selected targets and offers a commit-first prompt before PR dispatch.
- Accepting the prompt reuses the existing commit route and only proceeds to PR creation if commit succeeds.
- Declining preserves current PR behavior, and cancelling aborts the dashboard PR command cleanly.
- Direct CLI/domain PR execution and headless/batch PR behavior remain unchanged.
- Targeted dashboard, action, and prompt-surface tests cover the new flow and its clean/dirty/cancel/failure edge cases.

## Risk register (trade-offs or missing tests)
- Risk: the existing commit action stages all files with `git add -A`, so operators may commit untracked files when they expected only already-staged changes.
  - Mitigation: make the prompt copy explicit that accepting uses the normal commit action for the selected target scope, including unstaged/untracked changes.
- Risk: adding a new dashboard confirmation surface could reintroduce interactive input regressions in legacy/Textual fallback paths.
  - Mitigation: prefer a small shared dialog helper with explicit fallback coverage and targeted UI tests.
- Risk: multi-target flows can still end in a partially advanced local state if one target commits successfully and a later target fails before PR creation.
  - Mitigation: abort the PR phase on the first commit failure, surface existing commit failure details, and keep the plan/documentation explicit about this safe-stop behavior.

## Open questions (only if unavoidable)
- None.
