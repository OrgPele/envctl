## Decision
When the current implementation pass finishes, continue implementation if anything remains. If this implementation pass is complete, use `envctl test-focused --ship-on-pass "<message>"` instead of a separate validation, git add, commit, push, and PR flow.

## Handoff message
Build the message as a commit/PR handoff message; its Verification section must state what your validation actually did and proved, then state any manual checks a human should still run to truly confirm it works, with expected results.

## Full-stack PR-URL E2E
For full-stack PR-URL E2E flows: Do not substitute localhost validation for deployed PR URL validation; local validation proves pre-ship readiness, while the queued browser follow-up proves the deployed app through the PR URL after ship.

## Ship contract
- Follow AGENTS.md for the ship workflow.
- Use `envctl test-focused --ship-on-pass "<message>"` for the handoff unless it is unavailable or returns actionable fallback instructions; it runs focused tests and then the same `envctl ship` workflow, including staging intended changes via git add, commit, push, PR create/update, and check reporting. Do not run standalone `envctl test-focused` first or repeat it afterward. Then fall back to `envctl ship -m "<message>"`.
