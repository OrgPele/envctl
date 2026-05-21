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
2. Determine the current worktree/project name, run `envctl test-plan --project <current-worktree-name> --json`, then run the focused commands it recommends.
3. If tests fail, investigate and fix the failures when they are caused by the current implementation, then rerun the relevant validation until the tree is in a good state or you have a concrete blocker. Run broad validation when the test plan recommends it or the change is cross-cutting/risky.
4. For runtime or browser-visible work, use project-scoped envctl helpers before handoff:
   - `envctl endpoints --project <current-worktree-name> --json` to read canonical active URLs and dependency ports.
   - `envctl qa-user ensure --project <current-worktree-name> ... --json` when deterministic auth credentials are needed.
   - `envctl playwright --project <current-worktree-name> -- <command>` for Playwright/browser tests against the active frontend.
   - If this prompt is installed as a Codex skill or direct prompt, you may also use available Codex skills named in the session, such as `$browser`, for browser verification.
5. Update `.envctl-commit-message.md` so the next commit message reflects the finalized implementation accurately.
6. Run `envctl ship --project <current-worktree-name> --json` to commit, push, create or reuse the PR, and report status checks. Fall back to `envctl commit`, `envctl pr`, and GitHub CLI checks only if `ship` is unavailable or blocked by the environment.
7. Inspect all unresolved PR review comments and review threads, address ALL actionable comments, commit and push any follow-up fixes, then wait for final PR confirmation/status checks before closing out the task. If comments are already resolved or non-actionable, report that evidence.

## Non-negotiables
- Prefer `envctl` commands over ad hoc test commands for the final validation pass.
- Do not claim success without running the focused commands from `envctl test-plan --project <current-worktree-name> --json`.
- If validation fails and you cannot resolve it safely, stop before commit/push/PR and report the blocker clearly.
- Keep `.envctl-commit-message.md` focused on one complete next commit message. Treat `### Envctl pointer ###` as the boundary after the last successful commit; everything after it is the next default commit message.
- Preserve repo conventions and avoid unrelated cleanup.

## Final response format
1. Validation commands run.
2. Validation results.
3. Finalization changes made (if any).
4. Commit / push / PR status.
5. Residual risks or blockers (only if needed).
