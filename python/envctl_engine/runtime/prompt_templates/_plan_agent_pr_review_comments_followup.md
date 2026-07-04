$gh-address-comments

## Objective
Inspect unresolved PR review comments and review threads on the current branch PR, address all actionable comments, update tests as needed, then use `envctl test-focused --ship-on-pass "<message>"` instead of running separate validation, git add, commit, push, and PR commands.

## Comment triage
- Treat unresolved review threads as the source of truth.
- Fix every actionable comment in code or tests.
- If every comment is already resolved or non-actionable, report that evidence instead of making unnecessary edits.

## Handoff message
Build the message as a commit/PR handoff message; its Verification section must state what your validation actually did and proved, then state any manual checks a human should still run to truly confirm it works, with expected results.

## Ship contract
- Follow AGENTS.md for the ship workflow.
- Use `envctl test-focused --ship-on-pass "<message>"` for the handoff unless it is unavailable or returns actionable fallback instructions; it runs focused tests and then the same `envctl ship` workflow, including staging intended changes via git add, commit, push, PR create/update, and check reporting. Then fall back to `envctl ship -m "<message>"`.
