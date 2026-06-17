## Decision
When the current implementation pass finishes, continue implementation if anything remains. If this implementation pass is complete, run focused validation with `envctl test-focused`, then use `envctl ship -m "<message>"` instead of a separate commit/push/PR flow.

## Handoff message
Build the message as a commit/PR handoff message; its Verification section must state what your validation actually did and proved, then state any manual checks a human should still run to truly confirm it works, with expected results.

## Full-stack PR-URL E2E
For full-stack PR-URL E2E flows: Do not substitute localhost validation for deployed PR URL validation; local validation proves pre-ship readiness, while the queued browser follow-up proves the deployed app through the PR URL after ship.

## Ship contract
- If a real subagent or background-task tool is available, delegate `envctl ship -m "<message>"` there.
- If no real background tool is available, run `envctl ship -m "<message>"` normally.
- Run bare `envctl ship` from inside the current worktree/project directory; add `--project <current-worktree-name>` only when operating from elsewhere.
- `ship` commits, pushes, creates a PR when none exists, reuses or updates the existing PR otherwise, predicts merge conflicts, waits for target GitHub Tests checks until they pass, fail, time out, or report no target check contexts, and returns the structured JSON PR status-check payload by default with `pr_created`, `operation_statuses`, `checks_state`, `passed_checks`, `failing_checks`, `pending_checks`, and `checks_error`.
- Do not run raw `git`, `gh`, or separate commit/PR/status commands unless `ship` is unavailable or failed with actionable fallback instructions.
- The shipping subagent must report commit/push/PR failures, merge conflicts, failed PR checks, pending-check timeout, no-checks-reported status, and actionable review comments immediately.
- Keep moving locally; do not wait for a successful ship result, and only return to the shipping lane if the subagent reports an issue.
- A successful ship result is silent: the shipping subagent must not send a success summary, JSON payload, or completion message back to the main agent.
