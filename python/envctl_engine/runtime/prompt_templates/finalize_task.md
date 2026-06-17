You are finalizing an implementation that should already be substantially complete in the current worktree.
Authoritative source of truth: current `MAIN_TASK.md`, current repo state, and the implementation already present in this worktree.
First verify what changed, then run envctl validation and prepare the branch for handoff.
Final output must include: validation commands run, results, finalization changes, commit/PR status, and residual risks or blockers.
WORKTREE BOUNDARY IS STRICT: MAKE ALL FILE EDITS ONLY INSIDE THE CURRENT CHECKED-OUT WORKTREE / REPO ROOT.

## Inputs
Primary source of truth: current `MAIN_TASK.md`
Additional instructions (optional):
$ARGUMENTS

## Workflow
1. Read `MAIN_TASK.md` and inspect the current repo state. Use injected code-intelligence context when present; otherwise follow repo-local guidance and use `rg` for exact strings. Use Serena, CGC/CodeGraphContext, CodeGraph, or another graph tool only when configured and relevant.
2. Run `envctl test-focused` from inside the current generated worktree. From elsewhere, use `envctl test-focused --project <current-worktree-name>`.
3. If validation fails because of the current implementation, fix it and rerun relevant validation. Run broader validation when the plan or risk requires it.
4. For runtime/browser-visible work, use project-scoped helpers before handoff:
   - `envctl endpoints --project <current-worktree-name> --json`
   - `envctl qa-user ensure --project <current-worktree-name> ... --json`
   - `envctl playwright --project <current-worktree-name> -- <command>`
   - available Codex skills such as `$browser`, when installed in the session
5. Compose one complete commit/PR handoff message and pass it inline with `envctl ship -m "<message>"`. Its Verification section must state what validation proved and list any remaining human checks with expected results.
6. Run `envctl ship -m "<message>"` from inside the current worktree; add `--project <current-worktree-name>` only when operating from elsewhere, as in `envctl ship --project <current-worktree-name> -m "<message>"`.
7. Let `ship` own commit, push, PR create/update, merge-conflict prediction, and GitHub Tests waiting. Delegate `ship` to a real subagent/background tool when available; that worker reports only merge conflicts, commit/push/PR failures, failed checks, pending-check timeout, no-checks-reported status, or actionable review comments. A successful ship result is silent.
8. Do not run raw `git`, `gh`, or separate commit/PR/status commands unless `ship` is unavailable or gives actionable fallback steps.
9. If `ship` returns `status: "merge_conflicts"`, resolve using its `merge_conflicts` payload, rerun validation, and run `ship` again.
10. Only inspect PR review comments when `ship` reports actionable review-comment status or when the dedicated PR review-comments follow-up prompt is running.

## Non-negotiables
- Prefer `envctl` commands over ad hoc test commands for the final validation pass.
- Do not claim success without running `envctl test-focused` from inside the current generated worktree, or the project-scoped equivalent when operating outside it.
- Prefer inline `-m "<message>"`; reserve `envctl commit` for fallback or commit-only maintenance cases.
- Do not write envctl-local commit-message ledger files.
- Preserve repo conventions and avoid unrelated cleanup.

## Final response format
1. Validation commands run.
2. Validation results.
3. Finalization changes made, if any.
4. Commit / push / PR status.
5. Residual risks or blockers only if needed.
