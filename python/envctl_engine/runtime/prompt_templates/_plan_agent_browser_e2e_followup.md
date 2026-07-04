$browser

## Objective
After the implementation commit is pushed, the PR is created or updated, and GitHub status checks have completed successfully, run browser-based E2E validation against the deployed website. Re-read the initial `MAIN_TASK.md` and verify that the requested feature is completely implemented end-to-end.

## URL source
If the preceding `envctl test-focused --ship-on-pass` or `envctl ship` output returned a non-empty `deployment_url`, use that exact URL. It is the deployed website and must receive the thorough browser E2E pass.

If no `deployment_url` was returned, derive the validation URL from the repository/PR naming convention, not from the PR body, comments, handoff text, envctl state, GitHub deployment statuses, or localhost/runtime-address sections. Use this exact flow, adjusting only if `jq` is unavailable:

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

## Guardrails
Do not start services, discover runtime targets, create users, run `envctl`, query GitHub deployments, or invent a localhost URL on your own. If the conventional URL is not reachable, report that as the blocker and include the exact PR number, repo name, URL attempted, and observed browser/network failure.

## Validation steps
1. Use the PR body only to understand the implementation request and any listed manual verification checks; never use it as the source for the browser URL.
2. Extract every manual/human check from the Verification section and try to perform every automatable check yourself through the deployed website URL, especially browser or E2E checks.
3. If credentials are required, use only credentials explicitly provided in the PR/handoff or deployment comment.
4. Because this follow-up is a Codex prompt, you may use the available `$browser` skill when it is installed in the session.
5. If the feature is browser-visible or can be observed through the browser, prove it is visible in the browser and capture evidence. Exercise the core acceptance criteria, critical user flows, and relevant edge/error states; do not stop at a page-load smoke test.
6. You must fix any issue, regression, or mismatch introduced by the implementation before final handoff, then rerun the relevant checks against the deployed website URL and report what each check proved.
7. Do not silently skip checks that were handed to a human: if a check is genuinely not automatable from this environment, name it, explain why, and state the exact remaining human confirmation with expected results.

## Final response
- PR number, repo name, and exact deployment URL tested.
- Browser checks performed and what each proved.
- Issues fixed, if any, plus rerun evidence.
- Manual checks that remain, only when genuinely not automatable, with expected results.
