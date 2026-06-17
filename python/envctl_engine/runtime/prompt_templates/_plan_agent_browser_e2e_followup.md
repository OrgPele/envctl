$browser

After the implementation commit is pushed, the PR is created or updated, and GitHub status checks have completed successfully, run browser-based E2E validation against the conventional deployment URL for the current PR. Re-read the initial `MAIN_TASK.md` and verify that the requested feature is completely implemented end-to-end.

Find the validation URL from the repository/PR naming convention, not from the PR body, comments, handoff text, envctl state, GitHub deployment statuses, or localhost/runtime-address sections. Use this exact flow, adjusting only if `jq` is unavailable:

```sh
PR_JSON="$(gh pr view --json number,url,body)"
PR_NUMBER="$(printf '%s' "$PR_JSON" | jq -r '.number')"
REPO_NAME="$(
  gh repo view --json name --jq '.name' |
    tr '[:upper:]' '[:lower:]' |
    sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//'
)"
DEPLOYMENT_URL="https://${REPO_NAME}-pr-${PR_NUMBER}.srv1512613.hstgr.cloud/"

printf 'PR #%s conventional deployment URL: %s\n' "$PR_NUMBER" "$DEPLOYMENT_URL"
test -n "$REPO_NAME"
test -n "$DEPLOYMENT_URL"
```

Use `$DEPLOYMENT_URL` as the browser validation URL. For example, PR 287 in `pele-monorepo` should validate `https://pele-monorepo-pr-287.srv1512613.hstgr.cloud/`.

Do not start services, discover runtime targets, create users, run `envctl`, query GitHub deployments, or invent a localhost URL on your own. If the conventional URL is not reachable, report that as the blocker and include the exact PR number, repo name, URL attempted, and observed browser/network failure.

Use the PR body only to understand the implementation request and any listed manual verification checks; never use it as the source for the browser URL. Extract every manual/human check from the Verification section and try to perform every automatable check yourself through the conventional deployment URL, especially browser or E2E checks. If credentials are required, use only credentials explicitly provided in the PR/handoff or deployment comment. Because this follow-up is a Codex prompt, you may use the available `$browser` skill when it is installed in the session. If the feature is browser-visible or can be observed through the browser, prove it is visible in the browser and capture evidence. You must fix any issue, regression, or mismatch introduced by the implementation before final handoff, then rerun the relevant checks against the conventional deployment URL and report what each check proved. Do not silently skip checks that were handed to a human: if a check is genuinely not automatable from this environment, name it, explain why, and state the exact remaining human confirmation with expected results.
