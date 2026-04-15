# envctl 1.6.2

`envctl` 1.6.2 is a patch release on top of `1.6.1`. It fixes two workflow regressions in the tmux-backed planning path: headless plan runs no longer launch tmux agent sessions, and plan runs now refuse to create a second tmux session for the same worktree and instead show the operator how to attach to the existing one.

## Why This Release Matters

`1.6.1` shipped the updated planning/session workflow, but two operator-facing edge cases were still wrong:

- `--headless --plan ... --tmux` still launched a tmux AI session even though headless mode should stay non-interactive and non-launching
- rerunning a tmux plan for the same worktree created another suffixed tmux session instead of treating the existing worktree session as the thing to attach to

This patch release corrects both behaviors without changing the broader planning flow.

## Highlights

### Headless plan runs now stay headless

- headless plan mode no longer launches plan-agent tmux sessions
- the headless path stays output-only and avoids interactive attach behavior

### Existing worktree sessions now fail fast with attach guidance

- if a specific worktree already has an envctl tmux session, plan launch stops instead of creating a new suffixed session
- envctl prints the exact `tmux attach-session -t ...` command for the existing session
- this check is worktree-root aware rather than only repo-session-name aware

## Included Changes

- startup gating now suppresses plan-agent terminal launch in headless plan mode
- tmux plan-agent launch detects existing sessions for the same worktree root and returns attach guidance
- release metadata updated for `1.6.2`

## Operator Notes

- `envctl --plan <selector> --headless --tmux` should no longer create a tmux AI session as a side effect
- `envctl --plan <selector> --tmux` now errors if that worktree already has an envctl tmux session and tells you how to attach to it

## Summary

`envctl` 1.6.2 is a focused patch release that makes tmux-backed planning more truthful in headless mode and safer when a worktree already has an active envctl session.
