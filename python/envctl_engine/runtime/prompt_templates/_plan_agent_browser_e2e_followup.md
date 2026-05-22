$browser

Run browser-based E2E validation after the implementation commit is pushed, the PR exists, and required GitHub checks have completed successfully.

Workflow:
1. Re-read `MAIN_TASK.md` and verify the feature is completely implemented end-to-end.
2. Use injected localhost addresses when present. If they are missing or stale, start `envctl --entire-system --headless` yourself and read real addresses from envctl state/health output.
3. Prefer `envctl endpoints --project <current-worktree-name> --json` for active URLs, `envctl qa-user ensure --project <current-worktree-name> ... --json` for deterministic auth, and `envctl playwright --project <current-worktree-name> -- <command>` for browser tests against the active frontend.
4. Use the available `$browser` skill when browser observation is useful, and prove browser-visible behavior is visible in the browser.
5. You must fix any issue, regression, or mismatch introduced by the implementation, rerun relevant checks, stop the exact runtime scope you started, and report evidence.
