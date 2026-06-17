When the current implementation pass finishes, validate with `envctl test-focused`, then hand off with `envctl ship -m "<message>"`.

Success criteria:
- The message is a complete commit/PR handoff: scope, important files/modules, tests run with results, config/env/migration notes, and risks.
- Its Verification section says what validation proved and lists any remaining human checks with expected results.
- `ship` runs from the current worktree; use `--project <current-worktree-name>` only if you are operating from elsewhere.
- `ship` owns commit, push, PR create/update, merge-conflict prediction, and GitHub Tests waiting. Use raw `git`, `gh`, or separate PR/status commands only when `ship` is unavailable or gives explicit fallback steps.
- If a real subagent/background task tool exists, delegate `ship` there and keep working on non-overlapping follow-up while checks are pending. The worker reports only failures, merge conflicts, failed checks, pending-check timeout, no-checks-reported status, or actionable review comments.
- A successful ship result is silent: the shipping worker must not send a success summary, JSON payload, or completion message back to the main agent.
