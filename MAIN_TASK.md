# Envctl Review Base-Branch Diff Plan For Single Mode

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Make `envctl review` in single mode show the full diff from the branch the worktree was created from, instead of only reporting the current worktree status against `HEAD`.
  - Keep the behavior deterministic for both the built-in Python review path and the optional repo-local helper path.
  - Preserve operability for existing detached worktrees by defining an explicit fallback chain and an override flag.
- Non-goals:
  - Reworking grouped review semantics beyond plumbing an explicit base branch when one is supplied.
  - Changing PR creation semantics in `run_pr_action`; the PR path is only a source of reusable base-resolution helpers.
  - Recovering the true historical origin branch for already-existing detached worktrees when no persisted provenance exists.
- Assumptions:
  - The public CLI surface should add `--review-base <branch>` as the primary override for review behavior.
  - Worktree provenance should live in a repo-local ignored state directory, not in `RunState`, because review needs the data even when no runtime session exists.
  - `.envctl-state/` is the correct persistence home because the codebase already uses it for per-project runtime preparation artifacts in `python/envctl_engine/startup/service_bootstrap_domain.py`.

## Goal (user experience)
When a user runs `envctl review --project <tree>` in single mode, the output should explicitly say which base branch was used, how that base was resolved, and show the full branch-relative diff from the merge-base with that branch through the current worktree state. New worktrees created by `envctl` should remember their origin branch automatically. Older or manually-created worktrees should still produce useful output by falling back to an explicit override, branch upstream, or the repo default branch.

## Business logic and data model mapping
- CLI and route parsing:
  - `python/envctl_engine/runtime/command_router.py`
    - `_store_value_flag(...)`
    - command token normalization for `review`
- Action env propagation:
  - `python/envctl_engine/actions/action_command_support.py`
    - `build_action_extra_env(...)`
    - `build_action_env(...)`
- Review dispatch and execution:
  - `python/envctl_engine/actions/action_command_orchestrator.py`
    - `run_review_action(...)`
  - `python/envctl_engine/actions/actions_analysis.py`
    - `default_review_command(...)`
  - `python/envctl_engine/actions/actions_cli.py`
    - `main(...)`
  - `python/envctl_engine/actions/project_action_domain.py`
    - `run_review_action(...)`
    - `_analysis_iterations(...)`
    - `_run_analyze_helper(...)`
    - `detect_default_branch(...)`
    - `_pr_base_ref(...)`
- Worktree creation and provenance capture:
  - `python/envctl_engine/planning/worktree_domain.py`
    - `_create_single_worktree(...)`
    - `_create_feature_worktrees(...)`
    - existing placeholder fallback in `_worktree_add_failure(...)`
- Persistence model:
  - Keep runtime `RunState` unchanged for this feature; `python/envctl_engine/state/models.py:RunState.metadata` is session-scoped and currently only captures runtime command metadata.
  - Add a new worktree-local provenance artifact under `<worktree>/.envctl-state/worktree-provenance.json`, with fields such as:
    - `schema_version`
    - `source_branch`
    - `source_ref`
    - `resolution_reason`
    - `created_from_repo`
    - `recorded_at`

## Current behavior (verified in code)
- `review` is routed through the Python action stack, not a shell script:
  - `python/envctl_engine/actions/action_command_orchestrator.py:420-431` dispatches `review` via `ENVCTL_ACTION_ANALYZE_CMD` or the Python default command.
  - `python/envctl_engine/actions/actions_analysis.py:9-15` resolves the default review command to `python -m envctl_engine.actions.actions_cli review`.
  - `python/envctl_engine/actions/actions_cli.py:37-43` sends both `review` and `analyze` to `project_action_domain.run_review_action(...)`.
- The built-in review implementation does not compare against a base branch:
  - `python/envctl_engine/actions/project_action_domain.py:147-200`
  - It writes markdown from:
    - `git diff --stat`
    - `git status --porcelain`
  - This is current-worktree-vs-`HEAD` output, not branch-relative review output.
- The repo-local helper path has no explicit base-branch contract today:
  - `python/envctl_engine/actions/project_action_domain.py:155-165` prefers `utils/analyze-tree-changes.sh` if it exists and is executable.
  - `_run_analyze_helper(...)` at `python/envctl_engine/actions/project_action_domain.py:523-584` passes `trees=`, `approach=`, `output-dir=`, optional `scope=`, and optional quality checks, but no base branch.
- Single-mode review selection is target selection only:
  - `_analysis_iterations(...)` at `python/envctl_engine/actions/project_action_domain.py:479-495` returns only the current iteration for `single`, or all siblings for `grouped`.
  - No code in this path resolves or persists a diff baseline.
- Worktree creation currently loses source-branch provenance:
  - `python/envctl_engine/planning/worktree_domain.py:166-185`
  - `python/envctl_engine/planning/worktree_domain.py:921-950`
  - Both paths call `git worktree add --detach`, so the created worktree is intentionally detached and later cannot reliably answer “which branch was this checked out from?”
- Runtime state does not currently preserve review provenance:
  - `python/envctl_engine/state/models.py:113-122` defines `RunState.metadata`.
  - `python/envctl_engine/startup/finalization.py:60-76` only writes `command`, `repo_scope_id`, and `project_roots` for successful runs.
- Existing tests cover current helper/fallback behavior, but not origin-branch review behavior:
  - `tests/python/actions/test_actions_cli.py:683-947`
  - `tests/python/actions/test_actions_parity.py:493-821`
  - `tests/python/planning/test_planning_worktree_setup.py` currently validates worktree creation/deletion flows, but not provenance persistence.
- Current docs mention `review` but do not define its baseline:
  - `docs/reference/commands.md:73-76`
  - `docs/reference/commands.md:103-107`
  - `docs/user/common-workflows.md` has no review-specific guidance.

## Root cause(s) / gaps
- Review mode currently defines only which tree(s) to inspect, not which branch to compare against.
- Detached worktree creation deliberately discards branch attachment and does not persist provenance anywhere else.
- The built-in fallback path only reports working tree state against `HEAD`, so committed history relative to a base branch is not visible.
- The helper path cannot implement the requested behavior reliably because envctl never tells it what the base branch should be.
- There is no review-specific override equivalent to `--pr-base`, so users cannot correct ambiguous or legacy worktrees without changing code.
- The docs and automated tests do not lock the intended semantics, which makes regression likely.

## Plan
### 1) Define a review-base contract at the route and action-env layers
- Add `--review-base <branch>` to `python/envctl_engine/runtime/command_router.py` so the route can carry an explicit review baseline.
- Extend `python/envctl_engine/actions/action_command_support.py`:
  - `build_action_extra_env(...)` should map the route flag to `ENVCTL_REVIEW_BASE`.
  - Keep existing `ENVCTL_ANALYZE_MODE` and `ENVCTL_ANALYZE_SCOPE` behavior unchanged.
- Document the resolution order in code comments and docs so the feature is deterministic:
  1. explicit `--review-base` / `ENVCTL_REVIEW_BASE`
  2. persisted worktree provenance file
  3. current branch upstream if the target is on an attached branch
  4. repo default branch from `detect_default_branch(...)`
- Keep the new baseline semantics scoped to single mode. Grouped mode should preserve existing tree-selection behavior and only receive the explicit base if the user supplied one.

### 2) Persist source-branch provenance when envctl creates worktrees
- Introduce a small helper near `python/envctl_engine/planning/worktree_domain.py` to:
  - resolve the source branch before `git worktree add --detach`
  - write and read `<worktree>/.envctl-state/worktree-provenance.json`
- Capture provenance in both worktree-creation paths:
  - `_create_single_worktree(...)`
  - `_create_feature_worktrees(...)`
- Provenance resolution at creation time should be conservative:
  - prefer the current attached branch from the base repo when available
  - if the base repo is already detached, record the default branch instead and mark the `resolution_reason` accordingly
- Edge cases to handle explicitly:
  - `--setup-worktree-recreate`: overwrite provenance because a new detached worktree is being created.
  - `--setup-worktree-existing`: do not silently overwrite an existing provenance file; preserve prior origin metadata.
  - placeholder fallback (`.envctl_worktree_placeholder`): do not write fake provenance for failed `git worktree add` attempts.
  - flat tree roots (`trees-<feature>`) and nested roots (`trees/<feature>/<iter>`) must both use the same provenance file convention inside the actual worktree root.
- Do not add this data to `RunState.metadata` in phase one; review must work even when there is no prior runtime session.

### 3) Resolve the effective review base inside `run_review_action(...)`
- Add a dedicated review-base resolver in `python/envctl_engine/actions/project_action_domain.py` that:
  - reads `ENVCTL_REVIEW_BASE`
  - loads worktree provenance when the target root is a worktree
  - falls back to attached-branch upstream
  - falls back to `detect_default_branch(...)`
  - normalizes branch names through reusable ref helpers similar to `_pr_base_ref(...)`
- The resolver should also return metadata needed for the output bundle:
  - resolved base branch
  - resolved base ref
  - resolution source (`explicit`, `provenance`, `upstream`, `default_branch`)
  - merge-base SHA if available
- Error handling rules:
  - invalid explicit base branch should fail the review action with a clear actionable message
  - implicit fallback failures should degrade to the default branch only when that branch is verifiably resolvable
  - the output should always disclose when the base came from a fallback rather than persisted provenance
- For `project_root == repo_root` (`Main` mode target), skip provenance lookup and use the same fallback chain minus the worktree file.

### 4) Change built-in single-mode review output to branch-relative diff output
- Replace the current fallback content in `python/envctl_engine/actions/project_action_domain.py:167-189` with branch-relative reporting based on the resolved merge-base.
- Use merge-base-to-working-tree diff semantics so the review covers:
  - committed changes on the branch
  - staged changes
  - unstaged changes
- Recommended bundle sections for the built-in markdown output:
  - `Base branch`
  - `Base resolution source`
  - `Base ref`
  - `Merge base`
  - `Diff stat`
  - `Changed files`
  - `Full diff`
  - `Working tree / untracked files`
- Implementation detail:
  - Use the merge-base SHA as the left side of `git diff` rather than `base...HEAD` so the rendered diff includes current worktree changes, not only committed branch history.
  - Keep `git status --porcelain --untracked-files=all` (or equivalent) in a separate section because untracked files are not fully represented in `git diff <merge-base>`.
  - Enable rename detection for readability where practical.
- This step should preserve existing output-path behavior through `_tree_diffs_output_path(...)` and `_print_review_completion(...)`.

### 5) Pass the resolved base branch into repo-local review helpers
- Extend `_run_analyze_helper(...)` in `python/envctl_engine/actions/project_action_domain.py` to pass the resolved base branch explicitly, for example via `base-branch=<branch>` and optionally `base-source=<source>`.
- Keep helper invocation backward-compatible:
  - the new args should be additive
  - existing helpers that ignore unknown args should continue to work
- Update the helper contract in docs so repo-specific `utils/analyze-tree-changes.sh` implementations can align their analysis with the Python fallback.
- Keep helper preference intact; envctl should still defer to the helper when present, but now with enough context to implement the requested semantics.

### 6) Document the new semantics and migration behavior
- Update `docs/reference/commands.md` to define that single-mode `review` now compares against a resolved base branch, not merely the local worktree status.
- Update `docs/reference/important-flags.md` to document `--review-base`.
- Update `docs/user/common-workflows.md` or `docs/user/planning-and-worktrees.md` with:
  - how new worktrees remember their origin branch
  - how older/manual worktrees fall back
  - when to use `--review-base` explicitly
- Add a release/changelog note to `docs/changelog/main_changelog.md` when implementation lands so the semantic shift is visible to users and release reviewers.

## Tests (add these)
### Backend tests
- Extend `tests/python/actions/test_actions_cli.py` with:
  - a built-in review test proving `--review-base dev` drives branch-relative diff generation and is rendered in the output markdown
  - a provenance test proving `run_review_action(...)` reads `.envctl-state/worktree-provenance.json` when present
  - a fallback test proving missing provenance falls back to upstream branch, then default branch
  - an error-path test proving an invalid explicit base branch fails fast with an actionable message
  - a regression test proving untracked files still appear in the output even when the diff is generated from merge-base
- Extend `tests/python/actions/test_actions_parity.py` with:
  - route/env propagation coverage for `--review-base`
  - action env assertions that `ENVCTL_REVIEW_BASE` is present only when explicitly supplied
  - interactive/headless review parity checks that the new flag does not break existing routing
- Extend `tests/python/planning/test_planning_worktree_setup.py` with:
  - worktree creation writes `.envctl-state/worktree-provenance.json`
  - recreate flow overwrites provenance
  - existing-worktree reuse preserves existing provenance
  - placeholder fallback does not write a provenance file

### Frontend tests
- No frontend/browser tests are required for the first implementation because the feature is CLI/action-layer only and there is no current review-base selector UI.
- If a later change exposes review-base selection in the textual dashboard, add targeted UI tests there rather than broad frontend coverage now.

### Integration/E2E tests
- Add one end-to-end action-path test that simulates an envctl-created worktree, then runs `review` without `--review-base` and asserts the persisted provenance drives the reported base branch.
- Add one helper-path integration test in `tests/python/actions/test_actions_cli.py` proving the helper receives the new `base-branch=` argument when present.
- Add one main-repo integration test proving `review` on `Main` skips provenance and falls back to default-branch resolution cleanly.

## Observability / logging (if relevant)
- Emit review-base resolution events from `project_action_domain.py`, for example:
  - `review.base.resolved`
  - `review.base.provenance.missing`
  - `review.helper.base_forwarded`
- Include in the event payload:
  - `project`
  - `mode`
  - `base_branch`
  - `base_ref`
  - `resolution_source`
  - `merge_base`
- Keep user-facing output explicit even if events are not consumed, because review artifacts themselves are part of the debugging surface.

## Rollout / verification
- Implement behind the normal Python review path without a feature flag; the behavior change is user-visible but tightly scoped to `review` single mode.
- Verification checklist after implementation:
  1. Create a new worktree through envctl and confirm `.envctl-state/worktree-provenance.json` is written.
  2. Run `envctl review --project <tree>` and verify the summary prints the expected base branch and merge-base metadata.
  3. Run `envctl review --project <tree> --review-base <other-branch>` and verify the explicit override wins.
  4. Run review in a legacy worktree with no provenance file and verify the output states whether upstream or default-branch fallback was used.
  5. Run review with a repo-local helper and verify the helper receives the explicit base argument.
  6. Append a changelog entry to `docs/changelog/main_changelog.md` describing the semantic change once implementation lands.

## Definition of done
- `envctl review` single mode resolves a base branch deterministically and reports that resolution in the output.
- New envctl-created worktrees persist their origin branch under `.envctl-state/`.
- The built-in Python fallback emits branch-relative diff content, not only `git diff --stat` plus `git status`.
- Repo-local helpers receive the resolved base branch explicitly.
- Docs describe the new behavior, override flag, and legacy-worktree fallback chain.
- Automated tests cover explicit override, provenance lookup, fallback behavior, helper forwarding, and worktree provenance persistence.

## Risk register (trade-offs or missing tests)
- Existing detached worktrees created before this feature will not have true origin-branch provenance.
  - Mitigation: explicit `--review-base` override and transparent fallback-source reporting.
- Repo-local helpers may ignore the new `base-branch=` argument and continue producing old semantics.
  - Mitigation: keep the argument additive, document the contract, and add helper-path regression coverage.
- Rebases or deleted base branches can change the merge-base over time, so repeated reviews may not be byte-for-byte stable.
  - Mitigation: print both the resolved base ref and merge-base SHA in the review output.
- If the base repo is already detached at worktree-creation time, recorded provenance may necessarily fall back to the default branch rather than the true human intent.
  - Mitigation: persist the `resolution_reason` and keep explicit override available.

## Open questions (only if unavoidable)
- None. The explicit override plus fallback chain is sufficient to implement the feature without blocking product questions.
