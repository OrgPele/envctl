# envctl 1.6.6

`envctl` 1.6.6 is a hotfix release on top of `1.6.5`. It publishes two already-reviewed follow-up improvements from current `main`: clearer command-boundary documentation and a safer, better-verified OMX-managed planning bootstrap path.

## Why This Release Matters

`1.6.5` stabilized the tmux-backed planning workflow, but two follow-up areas still mattered for operator trust:

- command-surface boundaries were still implicit, which made it too easy to confuse launcher-owned commands, bootstrap-safe inspection commands, and full runtime commands
- OMX-managed `--plan ... --omx` launches needed to stay on the documented managed bootstrap path and recover existing worktree/session state more reliably from the real startup path

This hotfix release packages those improvements without widening the user-facing surface beyond the already-merged changes on `main`.

## Highlights

### Command boundaries are documented more clearly

- the command reference now includes a dedicated boundary section for launcher-owned commands, bootstrap-safe inspection/utility commands, and operational runtime commands
- onboarding now links directly to that boundary summary
- the distinction between `codex-tmux` and the optional post-`--plan` launch flow is explicit

### OMX-managed plan launches stay on the managed bootstrap path

- `envctl --plan ... --omx` keeps using the documented `omx --tmux` bootstrap contract
- existing-session recovery from the startup path now considers `--omx` the same way it already considered `--tmux`
- startup/runtime tests now cover OMX managed launch reuse and the session-unavailable path more directly

## Included Changes

- command-boundary documentation and validation-test coverage
- OMX managed-launch bootstrap hardening
- existing OMX session recovery through startup orchestration
- release metadata updated for `1.6.6`

## Operator Notes

- `docs/reference/commands.md` is now the authoritative quick summary for which commands are safe before bootstrap/runtime startup
- `envctl --plan <selector> --omx` continues to rely on OMX creating the managed tmux/Codex session rather than envctl creating a tmux window directly
- when an OMX-managed session already exists for the selected worktree, startup/output now has better coverage around attachable-session reuse
- release artifacts are expected under `dist/` after building the package

## Artifacts

This release publishes:

- wheel distribution
- source distribution

After build, the artifacts are expected under `dist/`.

## Summary

`envctl` 1.6.6 is a hotfix release focused on trust and clarity. It makes the command surface easier to reason about, keeps OMX-managed planning aligned with the documented bootstrap path, and ships the follow-up verification work needed to trust those flows in real startup behavior.
