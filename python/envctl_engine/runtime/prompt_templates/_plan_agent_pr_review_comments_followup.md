$gh-address-comments

## Objective
Inspect unresolved PR review comments and review threads on the current branch PR, address all actionable comments, update tests as needed, then use `envctl test-focused --ship-on-pass "<message>"` if focused validation has not already passed for the final tree. If focused validation already passed for the final tree, use `envctl ship -m "<message>"` and do not rerun tests.

## Comment triage
- Treat unresolved review threads as the source of truth.
- Fix every actionable comment in code or tests.
- If every comment is already resolved or non-actionable, report that evidence instead of making unnecessary edits.

## Handoff message
Build the message as a commit/PR handoff message; its Verification section must state what your validation actually did and proved, then state any manual checks a human should still run to truly confirm it works, with expected results.

## Ship contract
- Follow AGENTS.md for the ship workflow.
- Use `envctl test-focused --ship-on-pass "<message>"` for handoff unless focused validation already passed for the final tree, it is unavailable, or it returns actionable fallback instructions; it validates and then runs the standard ship workflow, including staging intended changes via git add, commit, push, PR create/update, and check reporting. Use `envctl ship -m "<message>"` when focused validation already passed or fallback is needed. Do not run standalone `envctl test-focused`, repeat passing tests, or run `envctl test --all` / other broad local suites.
- If ship returns a non-empty `deployment_url`, treat it as the deployed website and test it thoroughly E2E.
- If a PR URL exists after handoff, include it in the final response and repeat it as the final line when practical.
