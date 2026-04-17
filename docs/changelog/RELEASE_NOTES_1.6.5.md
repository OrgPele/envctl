# envctl 1.6.5

`envctl` 1.6.5 is a patch release on top of `1.6.4`. It fixes tmux-backed Codex cycle queuing, makes existing-session reuse clearer, and restores dependable AI launch or attach hints across plan worktrees.

## Why This Release Matters

`1.6.4` improved the tmux-backed planning workflow, but a few operator-facing gaps were still easy to trip over:

- tmux-backed Codex cycle mode could still behave like a single round in some plan-launch flows
- the existing-session prompt did not make it obvious that `y` attached while `n` created a fresh tmux session
- some worktrees still showed no useful AI action in the dashboard even though envctl could infer a plan launch or at least a project-scoped tmux fallback
- dashboard session matching could miss attachable tmux sessions when provenance or window names were the only reliable signals

This patch release focuses on those tmux and dashboard correctness gaps so the planning workflow behaves predictably when you launch, reuse, or revisit implementation worktrees.

## Highlights

### Tmux Codex cycle workflows now queue correctly

- tmux-backed Codex launches now append the remaining cycle prompts instead of silently collapsing to the first round
- queued direct prompts accept Codex pasted-content placeholders so follow-up rounds still tab-queue reliably
- the default Codex cycle count is now `2`, matching the documented commit/push/PR follow-up flow

### Dashboard AI guidance is reliable again

- tree dashboards now show `Run AI:` for every inferred plan worktree and fall back to `envctl --project <name> --tmux` when no plan selector resolves
- attachable tmux sessions can now be found from worktree provenance or matching window names, not just path matches
- fallback `Run AI:` commands are shell-quoted when project names need it

### Existing tmux-session reuse is less ambiguous

- the interactive prompt now explicitly says `Y=attach / n=create new session`
- review and dashboard plan resolution prefer active plans over archived copies when both exist

### Documentation and prompt contracts match the runtime

- command reference, configuration, and user playbooks now describe the `2`-cycle default consistently
- the installed `create_plan` prompt now tells users the runtime default is `2` unless they choose another value

## Included Changes

- tmux Codex cycle queuing for multi-round plan launches
- pasted-content-aware queue detection for direct Codex follow-up prompts
- explicit existing-session attach-vs-new wording for tmux reuse prompts
- dashboard AI launch fallbacks and attach matching for plan worktrees
- active-plan preference when both live and archived plan copies exist
- docs and installed prompt contract updates for the `2`-cycle default
- release metadata updated for `1.6.5`

## Operator Notes

- `envctl --plan <selector> --tmux` now keeps Codex follow-up cycles queued in the same tmux pane when cycle mode is enabled
- when envctl reports an existing tmux session, answering `y` attaches and answering `n` creates a fresh suffixed session
- tree dashboards should now either list attachable AI sessions or show a concrete `Run AI:` command for every known worktree
- release artifacts are expected under `dist/` after building the package

## Artifacts

This release publishes:

- wheel distribution
- source distribution

After build, the artifacts are expected under `dist/`.

## Summary

`envctl` 1.6.5 is a planning-workflow patch release. It makes tmux-backed Codex cycles behave like the documented multi-round workflow, clarifies existing-session reuse, and restores dependable dashboard AI launch guidance across plan worktrees.
