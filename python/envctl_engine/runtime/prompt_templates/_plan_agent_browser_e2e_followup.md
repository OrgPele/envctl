$browser

After the implementation is pushed, the PR exists, and GitHub status checks are green, validate the requested behavior in a browser against the conventional PR deployment URL. Re-read the initial `MAIN_TASK.md` before testing.

Derive the URL from the repository and PR number, not from the PR body, comments, handoff text, envctl state, GitHub deployment statuses, localhost, or runtime-address output. Use this flow, adjusting only if `jq` is unavailable:

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

Use `$DEPLOYMENT_URL` as the validation target. For example, PR 287 in `pele-monorepo` validates `https://pele-monorepo-pr-287.srv1512613.hstgr.cloud/`.

Do not start services, discover runtime targets, create users, run `envctl`, query GitHub deployments, or invent a localhost URL. If the conventional URL is unreachable, report the blocker with PR number, repo name, URL attempted, and observed browser/network failure.

Use the PR body only for implementation context and the manual checks listed in its Verification section; never use it as the source for the browser URL. Extract every manual/human check and try to perform every automatable check yourself through `$DEPLOYMENT_URL`. If credentials are required, use only credentials explicitly provided in the PR, handoff, or deployment comment. Verify the feature is completely implemented end-to-end, prove browser-visible behavior is visible in the browser with captured evidence, fix any issue introduced by the implementation, rerun the relevant checks against `$DEPLOYMENT_URL`, and report what each check proved. If a human check is not automatable from this environment, name it, explain why, and state the exact expected results for the remaining human confirmation.
