You are finalizing an implementation that should already be substantially complete in the current worktree.
Authoritative source of truth: the current `MAIN_TASK.md`, the current repo state, and the implementation already present in this worktree.
First, quickly verify what was changed, then run the envctl validation flow before preparing the branch for handoff.
Final output must include: validation commands run, results, what changed during finalization (if anything), and any residual risks.
WORKTREE BOUNDARY IS STRICT: MAKE ALL FILE EDITS ONLY INSIDE THE CURRENT CHECKED-OUT WORKTREE / REPO ROOT. NEVER MODIFY FILES IN SIBLING WORKTREES OR ANY PATH OUTSIDE THE CURRENT REPO ROOT.

## Inputs
Primary source of truth: current `MAIN_TASK.md`
Additional instructions (optional):
$ARGUMENTS

## Required workflow
1. Read `MAIN_TASK.md` and briefly inspect the current repo state so you understand what is being finalized.
2. Determine the current worktree/project name and run `envctl test --project <current-worktree-name>`.
3. If tests fail, investigate and fix the failures when they are caused by the current implementation, then rerun the relevant validation until the tree is in a good state or you have a concrete blocker.
4. Update `.envctl-commit-message.md` so the next commit message reflects the finalized implementation accurately.
5. Commit the work.
6. Push the branch.
7. Open the PR if none exists yet, or update the existing PR. In either case, make sure the PR title and body/message are finalized to a high standard: they should be detailed, accurate, polished, and should clearly reflect the shipped implementation, validation results, and any residual risks. Do not add a PR comment or PR review comment as part of this flow unless the user explicitly asks for that; update the PR title/body instead.

## Non-negotiables
- Prefer `envctl` commands over ad hoc test commands for the final validation pass.
- Do not claim success without actually running `envctl test --project <current-worktree-name>`.
- If validation fails and you cannot resolve it safely, stop before commit/push/PR and report the blocker clearly.
- Do not post PR comments or PR review comments unless the user explicitly asks for them.
- Keep `.envctl-commit-message.md` focused on one complete next commit message. Treat `### Envctl pointer ###` as the boundary after the last successful commit; everything after it is the next default commit message.
- Preserve repo conventions and avoid unrelated cleanup.

## Final response format
1. Validation commands run.
2. Validation results.
3. Finalization changes made (if any).
4. Commit / push / PR status.
5. Residual risks or blockers (only if needed).
