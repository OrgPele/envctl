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
   - Use the injected worktree code-intelligence context if envctl added one. Otherwise follow repo-local AGENTS.md/tooling guidance and use `rg` for exact strings; do not assume Serena, CodeGraph, or any other graph tool exists unless it is configured for this checkout and relevant to the question.
2. Compose one complete commit/PR handoff message and use `envctl test-focused --ship-on-pass "<message>"` from inside the current generated worktree as the single envctl local validation-and-handoff pass. Do not run standalone `envctl test-focused` first or repeat it afterward. When running from outside the worktree, include `--project <current-worktree-name>` on that same combined command.
3. If the combined command's tests fail, investigate and fix the failures when they are caused by the current implementation, then rerun `envctl test-focused --ship-on-pass "<message>"` until the tree is in a good state or you have a concrete blocker. Use additional repo-specific test commands only when diagnosing a failure or when the focused plan explicitly recommends broader validation for a cross-cutting/risky change.
4. For runtime or browser-visible work, prefer the repo's existing test harness and AGENTS.md guidance. Use project-scoped envctl helpers only when a local runtime is already running or the task/test harness explicitly requires one. If this prompt is installed as a Codex skill or direct prompt, you may also use available Codex skills named in the session, such as `$browser`, for browser verification.
5. Follow AGENTS.md for the ship workflow. The normal path is the combined `envctl test-focused --ship-on-pass "<message>"` command only; it runs focused tests and then the same `envctl ship` workflow, including staging intended changes via git add, commit, push, PR create/update, and check reporting. Fall back to `envctl ship -m "<message>"` only when the combined command is unavailable or returns actionable fallback instructions. Do not run `envctl commit` separately in the normal handoff path, and do not write envctl-local commit-message ledger files.
   - Its Verification section must state what your validation actually did and proved, then state any manual checks a human should still run to truly confirm it works, with expected results.
6. For full-stack PR-URL E2E flows, remember that the combined focused local validation-and-ship command is required but deployed PR URL E2E validation is an additional post-PR lane. Do not replace the queued deployed browser validation with localhost, local dev-server, or envctl runtime URL checks.
7. If `ship` returns `status: "merge_conflicts"`, use the `merge_conflicts` payload to resolve the conflict, rerun validation, and run `ship` again.
8. Only inspect PR review comments when `ship` reports actionable review-comment status or when the dedicated PR review-comments follow-up prompt is running. Otherwise, treat PR review handling as owned by `ship` status and the dedicated follow-up prompt.

## Non-negotiables
- Use `envctl test-focused --ship-on-pass "<message>"` as the final envctl validation pass and handoff in one command.
- Do not claim success after running standalone `envctl test-focused`; that duplicates the local test pass and skips the ship-on-pass contract.
- If validation fails and you cannot resolve it safely, stop before commit/push/PR and report the blocker clearly.
- Prefer inline `--ship-on-pass "<message>"` for the validation-and-ship handoff; reserve `envctl commit` for fallback or commit-only maintenance cases, and do not write envctl-local commit-message ledger files.
- Preserve repo conventions and avoid unrelated cleanup.

## Success criteria
- The implementation is verified against the current `MAIN_TASK.md`.
- The combined validation-and-handoff command has passed or a concrete blocker is reported before shipping.
- `envctl test-focused --ship-on-pass "<message>"` is the handoff path unless it is unavailable or returns actionable fallback instructions.
- Any deployed PR URL E2E requirement remains queued for the browser follow-up and is not replaced with localhost validation.

## Final response format
1. Validation commands run.
2. Validation results.
3. Finalization changes made (if any).
4. Commit / push / PR status.
5. Residual risks or blockers (only if needed).
