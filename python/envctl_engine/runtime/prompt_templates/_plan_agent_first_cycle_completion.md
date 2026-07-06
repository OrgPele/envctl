## Decision
When the current implementation pass finishes, continue implementation if anything remains. If the first pass is complete and focused validation has not already passed for the final tree, use `envctl test-focused --ship-on-pass "<message>"`. If focused validation already passed for the final tree, use `envctl ship -m "<message>"` and do not rerun tests.

## Handoff message
Build the message as a commit/PR handoff message; its Verification section must state what your validation actually did and proved, then state any manual checks a human should still run to truly confirm it works, with expected results.

## Full-stack PR-URL E2E
For full-stack PR-URL E2E flows: Do not substitute localhost validation for deployed PR URL validation; local validation proves pre-ship readiness, while the queued browser follow-up proves the deployed app through the PR URL after ship.
If ship returns a non-empty `deployment_url`, treat it as the deployed website and test it thoroughly E2E.

## Ship contract
- Follow AGENTS.md for the ship workflow.
- Use `envctl test-focused --ship-on-pass "<message>"` for handoff unless focused validation already passed for the final tree, it is unavailable, or it returns actionable fallback instructions; it validates and then runs the standard ship workflow, including staging intended changes via git add, commit, push, PR create/update, and check reporting. Use `envctl ship -m "<message>"` when focused validation already passed or fallback is needed. Do not run standalone `envctl test-focused`, repeat passing tests, or run `envctl test --all` / other broad local suites.
- If a PR URL exists after handoff, include it in the final response and repeat it as the final line when practical.
