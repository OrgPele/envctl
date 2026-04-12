# envctl 1.3.0

`envctl` 1.3.0 packages the latest workflow fixes that make day-to-day multi-worktree development less fragile: reviews now understand the branch a tree came from, envctl-created worktrees check out real branches instead of detached `HEAD`, and the PR selector behaves correctly under keyboard control.

This release is about operational trust. The underlying workflows already existed, but several sharp edges around detached worktrees, branch-relative review, and Textual selection state could still force users into manual recovery. `1.3.0` closes those gaps.

## Why This Release Matters

`envctl` is most valuable when you are actively comparing multiple implementations at once. That is also where the cost of subtle workflow mistakes is highest:

- reviews that only show the local dirty state instead of the full branch diff
- detached worktrees that skip PR creation or require manual branch checkout
- dashboard selectors that ignore the focused row and act on the wrong project

`1.3.0` addresses those failures directly so the review and PR flows behave like first-class parts of the tool, not fragile wrappers around Git state.

## Highlights

### Branch-relative review in single mode

Single-mode `envctl review` now resolves an explicit review base and shows the full branch-relative diff from the merge-base through the current worktree state.

- new `--review-base <branch>` override for deterministic review targeting
- envctl-created worktrees persist provenance in `.envctl-state/worktree-provenance.json`
- fallback resolution now uses provenance, upstream branch, or repo default branch
- built-in review output records the chosen base branch, ref, source, merge-base, diff stat, changed files, full diff, and working-tree status
- repo-local review helpers now receive the resolved base via additive `base-branch=`, `base-source=`, and `base-ref=` arguments

### Branch-attached envctl worktrees

New envctl-managed worktrees now check out named branches instead of being left detached.

- worktree creation uses envctl-managed branch names such as `<feature>-<iteration>`
- recreate flows reuse or reset the envctl branch deterministically
- detached-`HEAD` PR attempts now persist as `skipped` instead of a misleading success result

This removes a common source of confusion in PR and review workflows and makes new worktrees immediately usable for normal Git operations.

### PR selector keyboard reliability

The interactive PR selector now respects the focused row when toggling project selection with `Space`.

- initial selector focus/index are synchronized before the first navigation event
- row rebuilds preserve the live `ListView` cursor instead of snapping back to the top row
- `Space` toggles exactly the currently focused project before `Enter` confirmation

These fixes close the Textual regression where the first project could be selected even when a lower row had focus.

## Included Changes

Major areas covered in this release:

- review-base routing, provenance persistence, and branch-relative review output
- helper forwarding for resolved review-base metadata
- branch-attached worktree creation and recreate semantics
- PR action skip classification for detached worktrees
- Textual PR selector focus/index synchronization and focused-row toggle fixes
- follow-up test and contract stabilization for the updated workflows

## Artifacts

This release publishes:

- wheel distribution
- source distribution

After build, the artifacts are expected under `dist/`.

## Upgrade Note

If you are already using `envctl`, the most visible changes in `1.3.0` are:

- `review` now explains which base branch it used and shows the actual branch-relative diff
- new envctl worktrees come up on a branch instead of detached `HEAD`
- the PR selector now toggles the row you actually focused

Existing already-detached worktrees are not automatically reattached; recreating them through envctl or checking out a branch manually is still required to benefit from the new branch-attached workflow.

## Summary

`envctl` 1.3.0 makes review and PR workflows materially safer in the exact scenarios where multi-worktree development is most error-prone. The release centers on correct branch context, predictable Git state, and keyboard interactions that behave as the UI indicates.
