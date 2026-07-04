## Decision
When the current implementation pass finishes, continue implementation if anything remains. If the first implementation pass is complete, run focused validation with `envctl test-focused`, then use `envctl ship -m "<message>"` instead of a separate commit/push/PR flow.

## Handoff message
Build the message as a commit/PR handoff message; its Verification section must state what your validation actually did and proved, then state any manual checks a human should still run to truly confirm it works, with expected results.

## Full-stack PR-URL E2E
For full-stack PR-URL E2E flows: Do not substitute localhost validation for deployed PR URL validation; local validation proves pre-ship readiness, while the queued browser follow-up proves the deployed app through the PR URL after ship.

## Ship contract
- Follow AGENTS.md for the ship workflow.
- Use `envctl ship -m "<message>"` for the handoff unless it is unavailable or returns actionable fallback instructions.
