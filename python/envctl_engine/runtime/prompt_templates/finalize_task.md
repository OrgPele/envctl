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
2. Run `envctl test-focused` from inside the current generated worktree for focused validation. When running from outside the worktree, use `envctl test-focused --project <current-worktree-name>`.
3. If tests fail, investigate and fix the failures when they are caused by the current implementation, then rerun the relevant validation until the tree is in a good state or you have a concrete blocker. Run broad validation when the test plan recommends it or the change is cross-cutting/risky.
4. For runtime or browser-visible work, use project-scoped envctl helpers before handoff:
   - `envctl endpoints --project <current-worktree-name> --json` to read canonical active URLs and dependency ports.
   - `envctl qa-user ensure --project <current-worktree-name> ... --json` when deterministic auth credentials are needed.
   - `envctl playwright --project <current-worktree-name> -- <command>` for Playwright/browser tests against the active frontend.
   - If this prompt is installed as a Codex skill or direct prompt, you may also use available Codex skills named in the session, such as `$browser`, for browser verification.
5. Compose one complete commit message and pass it inline with `envctl ship -m "<message>"`; do not run `envctl commit` separately in the normal handoff path. Use `.envctl-commit-message.md` only as the fallback default-message ledger when inline `-m` is not practical.
6. Run `envctl ship -m "<message>"` from inside the current generated worktree. Run bare `envctl ship` from inside the current worktree/project directory; add `--project <current-worktree-name>` only when operating from elsewhere, as in `envctl ship --project <current-worktree-name> -m "<message>"`. It commits, pushes, creates a PR when none exists, reuses or updates the existing PR otherwise, predicts merge conflicts, waits for GitHub checks until they pass, fail, time out, or report no check contexts, and returns JSON by default with current status, `pr_created`, `operation_statuses`, `checks_state`, `passed_checks`, `failing_checks`, `pending_checks`, `checks_error`, and merge-conflict details. When subagents are available, delegate this `ship` run to a background subagent so the main thread can keep doing non-overlapping finalization work while CI is pending; do not block the main agent waiting for a successful ship result. The shipping subagent should send a message back only for merge conflicts, commit/push/PR failures, failed PR status checks, pending-check timeout, no-checks-reported status, or actionable review comments. Fall back to manual commit, PR, or GitHub CLI checks only if `ship` is unavailable or blocked by the environment.
7. If `ship` returns `status: "merge_conflicts"`, use the `merge_conflicts` payload to resolve the conflict, rerun validation, and run `ship` again.
8. Inspect unresolved PR review comments and review threads, address all actionable comments, commit and push follow-up fixes, then wait for final PR confirmation/status checks before closing out. If comments are already resolved or non-actionable, report that evidence.

## Non-negotiables
- Prefer `envctl` commands over ad hoc test commands for the final validation pass.
- Do not claim success without running `envctl test-focused` from inside the current generated worktree, or the project-scoped equivalent when operating outside that worktree.
- If validation fails and you cannot resolve it safely, stop before commit/push/PR and report the blocker clearly.
- Prefer inline `-m "<message>"` for `envctl ship`; reserve `envctl commit` for fallback or commit-only maintenance cases. Keep `.envctl-commit-message.md` focused on one complete next commit message only when using the fallback ledger; in that case, treat `### Envctl pointer ###` as the boundary after the last successful commit.
- Preserve repo conventions and avoid unrelated cleanup.

## Final response format
1. Validation commands run.
2. Validation results.
3. Finalization changes made (if any).
4. Commit / push / PR status.
5. Residual risks or blockers (only if needed).
