# envctl 1.1.0

`envctl` 1.1.0 is the first major step forward after the initial 1.0.0 release. This version focuses on making the CLI much more practical for day-to-day multi-worktree development: better dashboard flows, better test ergonomics, better prompt tooling, better configuration UX, and more reliable runtime behavior.

The core promise stays the same: bring up many isolated local environments without manual port juggling, shared-service collisions, or repetitive setup work. This release makes that promise much smoother in real usage.

## Why This Release Matters

Running one local stack is easy. Running five or ten worktree environments in parallel is where things usually fall apart:

- ports collide
- shared dependencies leak across worktrees
- app-specific env wiring drifts
- test, review, PR, and commit flows become inconsistent
- developers end up maintaining mental state instead of shipping changes

`envctl` exists to turn that into a deterministic system. It allocates ports, wires dependencies, keeps environments isolated, persists run state, and gives you one command surface for startup, tests, logs, health, review, PRs, commits, and cleanup across both `main` and `trees`.

`1.1.0` improves exactly those high-friction edges.

## Highlights

### Failed-only test reruns

You can now rerun only previously failing tests:

- `envctl test --failed`
- dashboard `t` flow now supports `Failed tests`
- backend reruns use exact saved pytest/unittest identifiers where supported
- frontend reruns use saved failed files
- saved failed-test manifests are persisted alongside human-readable summaries
- reruns fail closed on stale git state

This makes it much faster to iterate on broken worktrees without re-running the full suite every time.

### Much better dashboard UX

The interactive dashboard received a large usability pass:

- cleaner selector flows for worktrees and service scopes
- better grouping and preselection behavior
- spinner/final-status cleanup so command results don’t smear into spinner lines
- better handling of action failures and saved log paths
- improved summary rendering for test results and failed test artifacts
- better PR visibility and caching behavior

The goal was to make the dashboard feel like a reliable command center rather than a thin wrapper around subprocesses.

### Config wizard cleanup

The config wizard is now much more intentional:

- advanced-only flow
- cleaner component/dependency configuration
- improved wording and navigation behavior
- better handling of long-running backend-only services
- cleaner prompts, titles, button order, and text-entry behavior

This reduces setup confusion and makes `.envctl` initialization/editing easier to trust.

### Prompt preset and AI workflow improvements

Built-in prompt presets were simplified and modernized:

- prompt templates are now plain files, not overloaded with per-command metadata
- install flow works correctly for `all`
- preset naming and docs were cleaned up
- task-oriented presets now center around `MAIN_TASK.md`
- planning presets now align with `todo/plans/...`

This makes the prompt installation workflow much easier to understand and use across Codex/Claude/OpenCode style tooling.

### Runtime and startup reliability work

This release also includes important runtime fixes:

- more reliable startup/resume behavior
- clearer dependency failure messaging, including Docker requirements
- cleaner service log/test artifact path handling
- improved path printing and clickability in interactive output
- better compatibility handling in text-entry and selector UIs

These changes reduce the “tooling got in the way” class of failures during normal development.

## Included Changes

Major areas covered in this release:

- failed-only rerun support for backend and frontend
- test manifest persistence and failed-test summary improvements
- dashboard selector, spinner, and rendering UX improvements
- config wizard restructuring and copy cleanup
- commit/PR prompt and message workflow improvements
- prompt installer and built-in preset cleanup
- startup/runtime reliability fixes
- path rendering/log artifact UX improvements
- package/build cleanup and release packaging updates

## Artifacts

This release publishes:

- wheel distribution
- source distribution

After build, the artifacts are expected under `dist/`.

## Upgrade Note

If you are already using `envctl`, the biggest practical additions in `1.1.0` are:

- failed-only test reruns
- better dashboard behavior
- improved config wizard flow
- cleaner prompt installation behavior

## Summary

`envctl` 1.1.0 makes the tool substantially more usable for real multi-worktree development. The runtime model is the same, but the operational experience is better across configuration, testing, dashboard actions, prompt workflows, and failure handling.
