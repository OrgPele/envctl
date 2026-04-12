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

## 2026-03-16 - Fix follow-up test and contract drift

### Scope
Fixed follow-up regressions after the workflow changes by aligning the new PR flow test fixture with the shared selector model and resyncing runtime inventory contracts.

### Key behavior changes
- `tests/python/ui/test_pr_flow.py` now constructs valid branch `SelectorItem` fixtures with the current selector metadata shape.
- `tests/python/runtime/test_cutover_gate_truth.py` now writes a fresh parity-manifest timestamp so shipability assertions reflect runtime behavior instead of stale fixture data.
- Regenerated runtime inventory contracts to include the new review-base flag surface and the updated gap-report hash.

### Files and Modules Touched
- `tests/python/ui/test_pr_flow.py`
- `tests/python/runtime/test_cutover_gate_truth.py`
- `contracts/runtime_feature_matrix.json`
- `contracts/python_runtime_gap_report.json`

### Tests Run
- `PYTHONPATH=python python3 -m unittest tests.python.ui.test_pr_flow tests.python.runtime.test_cutover_gate_truth tests.python.runtime.test_runtime_feature_inventory`
  - Result: passed (`17` tests, `2` skipped because `textual` is not installed in this environment)
- `PYTHONPATH=python python3 -m unittest tests.python.planning.test_planning_worktree_setup tests.python.actions.test_action_command_orchestrator_targets tests.python.actions.test_actions_cli tests.python.ui.test_pr_flow tests.python.runtime.test_cutover_gate_truth tests.python.runtime.test_runtime_feature_inventory`
  - Result: passed (`67` tests, `2` skipped because `textual` is not installed in this environment)

### Config, Env, and Migrations
- No new config/env keys.
- No migrations.

### Risks and Notes
- The PR flow tests still skip without `textual` installed, so widget-level execution remains environment-dependent.

## 2026-03-16 - Fix PR flow keyboard index race after merge

### Scope
Hardened the PR flow selector against a render-timing race where rapid keyboard input could toggle the previously rendered row instead of the newly focused row.

### Key behavior changes
- `python/envctl_engine/ui/dashboard/pr_flow.py` now treats the app's cached list index as the source of truth for keyboard navigation, status text, and toggle actions.
- Row toggling no longer depends on `ListView.index` being updated before the next key event is processed.

### Files and Modules Touched
- `python/envctl_engine/ui/dashboard/pr_flow.py`

### Tests Run
- `PYTHONPATH=python python3 -m unittest tests.python.actions.test_action_command_orchestrator_targets tests.python.actions.test_actions_cli tests.python.actions.test_actions_parity tests.python.runtime.test_cli_router_parity`
  - Result: passed (`140` tests)
- `python3 -m py_compile python/envctl_engine/ui/dashboard/pr_flow.py`
  - Result: passed

### Config, Env, and Migrations
- No new config/env keys.
- No migrations.

### Risks and Notes
- Textual-specific PR flow execution still could not be run in this environment because `textual` is not installed here.

## 2026-03-16 - Fix immediate key handling in PR flow with Textual installed

### Scope
Resolved the remaining PR flow bug reproduced under a real Textual test environment where the first `Down` key could be overwritten by deferred selector setup, causing `Space` to keep toggling `Main`.

### Key behavior changes
- `python/envctl_engine/ui/dashboard/pr_flow.py` now renders the initial list synchronously on mount instead of leaving the first render on a background worker.
- PR flow list rebuilds preserve the live `ListView` index before clearing/re-extending rows.
- PR flow applies focus/index directly in this screen instead of relying on the deferred `focus_selectable_list(...)` sync path.
- `tests/python/ui/test_pr_flow.py` now asserts the status text via `status.render()` and pauses after directional input so the test matches current Textual widget semantics.

### Files and Modules Touched
- `python/envctl_engine/ui/dashboard/pr_flow.py`
- `tests/python/ui/test_pr_flow.py`

### Tests Run
- `PYTHONPATH=python /tmp/envctl-textual-venv/bin/python -m unittest tests.python.ui.test_pr_flow`
  - Result: passed (`2` tests)
- `PYTHONPATH=python python3 -m unittest tests.python.actions.test_action_command_orchestrator_targets tests.python.actions.test_actions_cli tests.python.actions.test_actions_parity tests.python.runtime.test_cli_router_parity`
  - Result: passed (`140` tests)
- `python3 -m py_compile python/envctl_engine/ui/dashboard/pr_flow.py`
  - Result: passed

### Config, Env, and Migrations
- No new config/env keys.
- No migrations.

### Risks and Notes
- Textual verification here used a temporary local venv at `/tmp/envctl-textual-venv`; that environment is not repo-managed.

## 2026-03-16 - Prepare envctl 1.3.0 release metadata and notes

### Scope
Cut the repository metadata and release collateral for `envctl` `1.3.0` on top of the current worktree changes so the branch is ready for a release PR, tag, and GitHub release.

### Key behavior changes
- Bumped the package version from `1.2.4` to `1.3.0` in `pyproject.toml`.
- Updated the README release badge/tag reference to `1.3.0`.
- Added `docs/changelog/RELEASE_NOTES_1.3.0.md` covering the three shipped release themes:
  - branch-relative single-mode review with persisted provenance
  - branch-attached envctl worktrees and detached PR skip truthfulness
  - PR selector keyboard/focus reliability fixes
- Added packaging tests that lock the `1.3.0` version metadata, README badge, and release-notes file together.

### Files and Modules Touched
- `pyproject.toml`
- `README.md`
- `docs/changelog/RELEASE_NOTES_1.3.0.md`
- `tests/python/runtime/test_cli_packaging.py`
- `docs/changelog/broken_review_fix-1_changelog.md`

### Tests Run
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_cli_packaging.CliPackagingTests.test_release_version_metadata_is_aligned_for_1_3_0 tests.python.runtime.test_cli_packaging.CliPackagingTests.test_release_notes_exist_for_1_3_0`
  - Result: passed
- `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_cli_packaging`
  - Result: passed

### Config, Env, and Migrations
- No new config/env keys.
- No migrations.
- New release-notes artifact: `docs/changelog/RELEASE_NOTES_1.3.0.md`

### Risks and Notes
- This release branch is intentionally based on the current worktree head so `1.3.0` includes the unreleased workflow fixes already implemented here.
