# envctl 1.4.0

`envctl` 1.4.0 is a minor release focused on AI-assisted planning and review workflows. It turns the post-`1.3.3` work on `main` into a shipped release: prompt installation is safer, worktree review has a dedicated preset, plan-agent launches are cleaner in cmux, nested tree layouts behave correctly, and Codex-backed tmux flows now have first-class runtime support.

This release is a minor instead of a hotfix because it adds new user-facing workflow surface rather than only correcting shipped behavior. The biggest changes are new prompt and runtime capabilities for planning, implementation, and review loops across local repos and generated worktrees.

## Highlights

### Prompt installation and origin-side review workflow

Prompt installation is now safer and more automation-friendly.

- repeat `install-prompts` runs overwrite in place after approval instead of creating `.bak-*` prompt siblings
- `--yes` and `--force` can pre-approve overwrites for non-interactive runs
- non-TTY and `--json` flows now fail cleanly when overwrite approval is required
- a new `review_worktree_imp` preset lets users review an implementation worktree while treating the current repo as the unedited baseline
- prompt installation now defaults to all available presets, including the new review path

### Better cmux planning behavior

Planning flows gained a cleaner and more reliable cmux experience.

- newly created plan-agent workspaces now reuse the starter surface when that surface is unambiguous instead of leaving an extra duplicate tab behind
- launch diagnostics distinguish reused starter surfaces from newly created ones
- nested custom trees layouts such as `work/trees` now resolve flat feature roots correctly across discovery, setup, and runtime startup metadata

### Codex tmux runtime support

`envctl` now ships an explicit Codex tmux workflow path for queued plan and implementation work.

- runtime command routing includes Codex tmux support for utility-command driven workflows
- PR action handling is stricter about dirty worktrees before PR creation
- planning artifacts are archived more consistently into `todo/done/` while active plans are carried forward

## Included Changes

Major areas covered in this release:

- prompt overwrite confirmation and clean non-interactive failure handling
- new `review_worktree_imp` prompt preset for origin-side worktree review
- prompt installation defaults expanded to the full preset inventory
- starter-surface reuse for newly created cmux plan-agent workspaces
- nested flat-worktree parity for custom `TREES_DIR_NAME` layouts
- Codex tmux workflow support in the runtime command path
- tighter PR-action handling around dirty worktrees
- docs and regression coverage updates for the new prompt, planning, and runtime paths

## Artifacts

This release publishes:

- wheel distribution
- source distribution

After build, the artifacts are expected under `dist/`.

## Upgrade Note

If you are already using `envctl`, the most visible changes in `1.4.0` are:

- installed AI prompt commands no longer accumulate `.bak-*` duplicates on normal overwrite flows
- worktree review now has a built-in origin-side preset instead of requiring ad hoc prompt setup
- cmux-backed `--plan` launches are cleaner when envctl has to create the target workspace
- repositories using nested custom trees roots behave correctly during worktree discovery and startup
- Codex tmux workflows can now be launched through the supported runtime path

## Summary

`envctl` 1.4.0 ships the next layer of AI-assisted repo workflow support. It makes prompt installation safer, review and planning flows more deliberate, and Codex/cmux runtime integration more capable without changing the core local-environment model.
