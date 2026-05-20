# envctl 1.6.0

`envctl` 1.6.0 is a minor release on top of `1.5.0`. It ships the workflow and safety improvements that landed after the `1.5.0` tag: stronger tmux/OpenCode planning defaults, clearer headless-vs-interactive plan follow-up behavior, inline dashboard AI session and run guidance, prompt-contract upgrades for implementation and plan flows, and a commit-safety fallback that keeps envctl-local artifacts out of user commits even when Git excludes are missing.

This release stays at a minor bump because the post-`1.5.0` range adds new user-facing planning, dashboard, and prompt workflow surface rather than only patching previously shipped internals.

## Why This Release Matters

The `1.5.0` line expanded envctl's workflow surface. `1.6.0` makes that workflow more complete and more trustworthy:

- tmux-backed AI planning and review flows now behave more like the product presents them, especially for OpenCode direct prompting and session handling
- dashboard AI affordances are clearer: users can see the live tmux attach surface for a running AI session or the exact command needed to launch one, but never both at the same time
- plan follow-up messaging now separates headless auto-run from interactive/manual execution and keeps attach instructions explicit when envctl launches the tmux session for the user
- shipped prompt templates now carry stronger execution contracts around end-of-task PR creation, CLI choice, cycle selection, and attach guidance
- envctl-managed local artifacts are safer because the commit path itself now refuses to stage them, even if the user’s Git excludes are incomplete

## Highlights

### Tmux/OpenCode planning and session workflow improvements

Planning flows now align better with the live tmux/OpenCode runtime model.

- tmux is the default plan-agent transport
- Opencode is the default AI CLI for plan-agent launch flows
- OpenCode direct prompting is now the default for tmux-backed plan-agent launches
- tmux plan runs no longer auto-attach by default, while attach instructions remain available when relevant
- session management and persistence now support richer dashboard/session workflows and explicit attach/kill handling

### Dashboard AI visibility and launch guidance

The interactive dashboard now presents AI session state and launch guidance more cleanly.

- per-project AI session rows use worktree-aware tmux matching instead of loose name heuristics
- attached state is determined from the active tmux session and pane path rather than only by session name
- the dashboard shows either:
  - a live `AI session` attach row, or
  - a `Run AI` launch command row
  but not both at the same time
- Run AI commands now match the supported interactive launch contract: `envctl --plan <selector> --tmux`

### Headless plan clarity and follow-up contract

Headless plan mode now behaves more truthfully and with less noise.

- headless plan follow-up output now centers on `session_id`, attach, and kill information rather than dropping into the interactive dashboard path in the changed startup flows
- generated follow-up guidance no longer misuses `--headless` for user-facing interactive/tmux launch commands
- startup follow-up text now distinguishes interactive/manual execution explicitly instead of implying the same command shape for every mode

### Prompt-contract upgrades for implementation and planning

The shipped prompts now better encode the intended workflow.

- `implement_task` now requires PR creation/update only at the very end of the implementation task, after implementation, tests, and commit are complete
- `implement_task` also explicitly includes PR status in the final response contract
- `create_plan` now offers AI CLI choice across:
  - `codex`
  - `opencode`
  - `both`
- when Codex is involved, `create_plan` now asks for Codex cycle count
- when the user chooses headless auto-run, `create_plan` now says envctl will print the attach command after launch so the user can attach to the tmux session

### Commit safety for envctl-local artifacts

envctl now has a stronger safety fallback for local-only files.

- envctl still maintains the existing global Git-excludes strategy for envctl-managed local artifacts
- in addition, `envctl commit` / `envctl pr` no longer rely on that alone
- commit flow now inspects `git status --porcelain --untracked-files=all`, skips protected envctl-local artifacts from staging, and fails fast if those files are already staged
- protected files include:
  - `.envctl*`
  - `MAIN_TASK.md`
  - `OLD_TASK_*.md`
  - `trees/`
  - `trees-*`

## Included Changes

Major areas covered in this release:

- tmux/OpenCode planning defaults and direct-prompt behavior improvements
- session history, attach/kill UX, and dashboard session visibility refinements
- per-project dashboard AI attach/run guidance with mutually exclusive row behavior
- headless plan output and follow-up command-contract cleanup
- prompt-template upgrades for `implement_task` and `create_plan`
- stronger commit-time protection for envctl-managed local artifacts
- focused docs/tests/runtime alignment for release and packaging metadata

## Operator Notes

- No data migration or manual config migration is required for this release.
- Teams using tmux-backed planning flows should see clearer session behavior and less ambiguity about how to attach or rerun manually.
- Users who rely on envctl-generated local task/state files should be better protected from accidentally committing those artifacts through envctl-managed commit/PR flows.
- Prompt-driven planning and implementation loops now carry stronger workflow guardrails, especially around CLI choice, PR ordering, and attach guidance.

## Artifacts

This release publishes:

- source-tagged GitHub release metadata

No binary artifacts are attached to the GitHub release draft for `1.6.0`.

## Upgrade Note

If you are already using `envctl`, the most visible changes in `1.6.0` are:

- clearer tmux/OpenCode session and attach behavior during planning and dashboard flows
- a cleaner dashboard AI presentation that separates live session attach from launch commands
- more truthful headless-vs-interactive follow-up guidance after plan creation
- stronger built-in prompt instructions for end-of-task PR creation and CLI/cycle selection
- safer envctl-managed commit/PR flows around `.envctl*`, task files, and worktree-local artifacts

## Summary

`envctl` 1.6.0 turns the planning, dashboard, prompt, and release-adjacent workflows into a tighter, more truthful system. The release makes tmux/OpenCode behavior easier to reason about, keeps AI/session affordances clearer, hardens the prompt contracts that drive implementation and planning, and adds a meaningful safety net so envctl-local artifacts stay out of user commits.
