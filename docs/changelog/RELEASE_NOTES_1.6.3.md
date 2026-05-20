# envctl 1.6.3

`envctl` 1.6.3 is a patch release on top of `1.6.2`. It tightens the tmux-backed planning workflow again: repeated plan launches can now reuse or intentionally fork worktree-scoped tmux sessions more predictably, headless guidance is clearer about when envctl reused an existing session, and the built-in `/create_plan` follow-up instructions now show the supported tmux launch commands instead of the older launcher env-var examples.

## Why This Release Matters

`1.6.2` fixed the biggest tmux planning regressions, but the operator flow still had rough edges:

- rerunning the same plan/workspace/CLI needed a clearer split between "attach to what already exists" and "create another tmux session on purpose"
- headless output showed the right commands, but it did not explicitly explain that envctl skipped creating a new session because one already existed
- `/create_plan` still documented stale launch examples and did not mention the supported `--tmux`, `--opencode`, or `--tmux-new-session` flow

This patch release keeps the worktree-scoped tmux model from `1.6.2`, adds a real force-new-session path, and aligns the prompt/install guidance with the commands users can actually run.

## Highlights

### Existing tmux sessions can now be reused or intentionally forked

- tmux plan-agent sessions are scoped by worktree path and CLI, so Codex and OpenCode for the same worktree no longer collide
- rerunning the same plan/workspace/CLI in interactive mode prompts the operator to attach to the existing session or create a new suffixed session
- answering `Enter`, `y`, or `yes` now reliably attaches to the existing tmux session instead of accidentally launching another one
- `--tmux-new-session` forces creation of a new suffixed tmux session even in interactive mode and skips the attach prompt entirely

### Headless mode gives clearer reuse instructions

- when a matching tmux session already exists, headless output now states that envctl reused the existing plan/workspace/CLI session instead of silently implying a fresh launch
- the printed `new session:` command now includes `--tmux-new-session --headless`, so copying that command really creates another tmux session instead of redisplaying the existing attach guidance

### `/create_plan` follow-up commands now match the supported launcher surface

- the built-in `create_plan` template now shows repo-scoped tmux launch commands such as `envctl --plan <selector> --tmux` and `envctl --plan <selector> --tmux --opencode`
- the template now documents `--tmux-new-session` for users who want another tmux session without being prompted
- the `both` option is still supported, but it is now documented as two separate envctl invocations run one after the other rather than one imaginary combined CLI mode

## Included Changes

- parser support for `--tmux-new-session`
- worktree-and-CLI-scoped tmux session naming plus suffixed `-2`, `-3`, ... creation for explicit new-session launches
- interactive attach/create prompting that defaults to attach and honors `y/yes/Enter`
- clearer headless reuse output with real force-new follow-up commands
- updated `create_plan` prompt-install template coverage for the supported tmux launcher commands
- release metadata updated for `1.6.3`

## Operator Notes

- use `envctl --plan <selector> --tmux` for Codex-backed tmux launches
- use `envctl --plan <selector> --tmux --opencode` for OpenCode-backed tmux launches
- use `--tmux-new-session` when you explicitly want another tmux session for the same plan/workspace/CLI without being prompted
- when selecting `both` from a prompt-driven follow-up, envctl should be run twice behind the scenes: once for Codex and once for OpenCode

## Artifacts

This release publishes:

- wheel distribution
- source distribution

After build, the artifacts are expected under `dist/`.

## Summary

`envctl` 1.6.3 is a focused tmux planning polish release. It makes repeated plan launches more predictable, makes headless reuse messaging more explicit, and keeps the built-in planning prompt guidance aligned with the commands envctl actually supports.
