$gh-address-comments

Inspect unresolved PR review comments and review threads on the current branch PR. Address every actionable comment, update tests as needed, run `envctl test-focused`, then hand off with `envctl ship -m "<message>"`.

Success criteria:
- If every comment is resolved or non-actionable, report that evidence instead of editing.
- The ship message is a complete commit/PR handoff. Its Verification section states what validation proved and lists any remaining human checks with expected results.
- `ship` runs from the current worktree; use `--project <current-worktree-name>` only if you are operating from elsewhere.
- `ship` owns PR create/update and GitHub Tests waiting. Use raw `git`, `gh`, or separate PR/status commands only when `ship` is unavailable or gives explicit fallback steps.
- If a real subagent/background task tool exists, delegate `ship` there. The worker reports only failures, merge conflicts, failed checks, pending-check timeout, no-checks-reported status, or new actionable review comments.
- A successful ship result is silent: the shipping worker must not send a success summary, JSON payload, or completion message back to the main agent.
