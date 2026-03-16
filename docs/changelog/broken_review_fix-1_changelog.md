# Worktree Changelog

## 2026-03-16 - Review base provenance and branch-relative single-mode review

### Scope
Implemented the `MAIN_TASK.md` review-base change end to end: route parsing, action env propagation, built-in review output, helper forwarding, worktree provenance persistence, and user docs.

### Key behavior changes
- Added `--review-base <branch>` routing and `ENVCTL_REVIEW_BASE` action env propagation for `review`.
- Single-mode review now resolves a base branch deterministically from explicit override, persisted worktree provenance, branch upstream, or repo default branch.
- Built-in review markdown now records:
  - base branch
  - base resolution source
  - base ref
  - merge-base
  - diff stat
  - changed files
  - full diff
  - working tree and untracked files
- Repo-local review helpers now receive `base-branch=...`, `base-source=...`, and `base-ref=...`.
- Envctl-created worktrees now persist provenance in `<worktree>/.envctl-state/worktree-provenance.json`.

### Files and Modules Touched
- `python/envctl_engine/runtime/command_router.py`
- `python/envctl_engine/actions/action_command_support.py`
- `python/envctl_engine/actions/project_action_domain.py`
- `python/envctl_engine/planning/worktree_domain.py`
- `tests/python/runtime/test_cli_router_parity.py`
- `tests/python/actions/test_actions_parity.py`
- `tests/python/actions/test_actions_cli.py`
- `tests/python/planning/test_planning_worktree_setup.py`
- `docs/reference/commands.md`
- `docs/reference/important-flags.md`
- `docs/user/planning-and-worktrees.md`
- `docs/changelog/main_changelog.md`

### Tests Run
- `PYTHONPATH=python python3 -m unittest discover -s tests/python/actions -t .`
  - Result: passed (`134` tests)
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_planning_worktree_setup tests.python.runtime.test_cli_router_parity tests.python.runtime.test_command_router_contract`
  - Result: passed (`39` tests)
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_cli_router_parity tests.python.actions.test_actions_parity tests.python.actions.test_actions_cli tests.python.planning.test_planning_worktree_setup`
  - Result: passed (`149` tests)

### Config, Env, and Migrations
- New CLI flag: `--review-base <branch>`
- New action env contract: `ENVCTL_REVIEW_BASE`
- New persisted repo-local artifact: `<worktree>/.envctl-state/worktree-provenance.json`
- No schema migrations or external service config changes

### Risks and Notes
- Existing detached/manual worktrees still depend on upstream or default-branch fallback when no provenance file exists.
- Review helpers must opt in to the new `base-branch=` arguments if they want output parity with the built-in implementation; older helpers remain callable because the args are additive.

## 2026-03-16 - Fix PR selector space key handling

### Scope
Fixed the pre-submit PR selector window so pressing `Space` toggles the current row once instead of only repainting the selector.

### Key behavior changes
- Removed the PR selector's duplicate `space` key handling path and aligned it with the shared selector pattern.
- Kept explicit `Enter` suppression for list selection so confirm still works without double-triggering.
- Added a Textual regression test covering `Space` in the PR selector before `Enter`.

### Files and Modules Touched
- `python/envctl_engine/ui/dashboard/pr_flow.py`
- `tests/python/ui/test_pr_flow.py`

### Tests Run
- `PYTHONPATH=python python3 -m unittest tests.python.ui.test_pr_flow tests.python.ui.test_text_input_dialog tests.python.ui.test_dashboard_orchestrator_restart_selector`
  - Result: passed (`42` tests, `4` skipped because `textual` is not installed in this environment)

### Config, Env, and Migrations
- No new config/env keys.
- No migrations.

### Risks and Notes
- The new PR flow regression test is skipped in this environment because the `textual` package is not installed here, so runtime validation depended on code-path review plus adjacent UI tests.

## 2026-03-16 - Fix PR selector focused-row toggle

### Scope
Corrected the PR selector so `Space` toggles the currently focused row instead of always acting on the cached top-row index.

### Key behavior changes
- PR selector toggle/status/navigation now derive focus from the live `ListView` index.
- Added a regression test for moving to the second row, pressing `Space`, and confirming that the second project is selected.

### Files and Modules Touched
- `python/envctl_engine/ui/dashboard/pr_flow.py`
- `tests/python/ui/test_pr_flow.py`

### Tests Run
- `PYTHONPATH=python python3 -m unittest tests.python.ui.test_pr_flow tests.python.ui.test_text_input_dialog tests.python.ui.test_dashboard_orchestrator_restart_selector`
  - Result: passed (`43` tests, `5` skipped because `textual` is not installed in this environment)

### Config, Env, and Migrations
- No new config/env keys.
- No migrations.

### Risks and Notes
- The focused-row regression still skips without `textual` installed, so end-to-end runtime verification of the actual widget stack remains deferred to an environment with Textual available.

## 2026-03-16 - Attach envctl worktrees to branches and persist detached PR skips

### Scope
Updated envctl-managed worktree creation so new trees check out a named branch, and corrected PR action persistence so detached-HEAD skips are recorded as `skipped` instead of `success`.

### Key behavior changes
- New worktrees now run through `git worktree add -b/-B <feature>-<iteration> <target> <start-point>` instead of `--detach`.
- Worktree start points resolve from the same source branch provenance used for review-base tracking, with a `HEAD` commit fallback when no branch ref is verifiable.
- Recreating a worktree reuses the same envctl branch name by resetting an existing local branch when needed.
- Dashboard/project action metadata now classifies detached-HEAD PR runs as `skipped`, which prevents misleading success state after `Skipping <project> (detached HEAD).`

### Files and Modules Touched
- `python/envctl_engine/planning/worktree_domain.py`
- `python/envctl_engine/actions/action_command_orchestrator.py`
- `tests/python/planning/test_planning_worktree_setup.py`
- `tests/python/actions/test_action_command_orchestrator_targets.py`

### Tests Run
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_planning_worktree_setup tests.python.actions.test_action_command_orchestrator_targets tests.python.actions.test_actions_cli`
  - Result: passed (`50` tests)

### Config, Env, and Migrations
- No new config/env keys.
- No migrations.

### Risks and Notes
- Existing already-detached worktrees are not automatically reattached; they still need a manual checkout or recreation to gain the new branch behavior.
- The new skip classification is intentionally scoped to PR actions that exit `0` while printing the detached-HEAD skip message.
