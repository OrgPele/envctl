# envctl 1.4.1

`envctl` 1.4.1 is a cumulative patch release on top of `1.4.0`. It ships the set of runtime and workflow fixes that landed after the `1.4.0` tag: safer prompt guidance for continuing work, startup-parity fixes for native migrate actions, stronger interrupt cleanup for envctl-managed test runs, and more reliable Codex plan-agent/cmux behavior.

This release stays at a patch bump because the work since `1.4.0` is corrective and hardening-oriented. The changes tighten already-shipped workflows instead of introducing a new advertised feature line.

## Why This Hotfix Matters

The post-`1.4.0` fixes all close gaps between the workflows envctl presents and the workflows it actually executes under stress.

- continue-task prompts now make users audit committed divergence from the originating branch, not only local dirty state
- native `migrate` actions inherit the same backend env and dependency projection assumptions as startup paths
- interrupted envctl-managed test runs clean up detached child suites instead of leaving stray processes behind
- Codex plan-agent cycles and starter-surface reuse now behave deterministically in real cmux-backed launches
- canonical release validation now ignores historical managed worktree copies and keeps the runtime feature inventory aligned with the shipped `codex-tmux` command

## Highlights

### Prompt provenance and divergence audit

The shipped `continue_task` prompt now tells users to inspect committed divergence from the originating branch or ref in addition to staged, unstaged, and untracked worktree changes.

- prompt guidance now calls out provenance and merge-base review explicitly
- prompt-install regression coverage locks the contract so installed templates stay aligned

### Native migrate actions now match startup env behavior

`envctl migrate` now reuses the same backend env-file resolution and dependency URL projection that startup paths already use.

- migrate actions can populate `DATABASE_URL` and `REDIS_URL` from saved run state when available
- explicit override database settings still keep precedence
- missing-env failures now explain the contract more clearly
- docs were updated across commands, configuration, and troubleshooting guidance

### Safer interrupt handling for envctl-managed tests

Interrupted test runs now terminate envctl-started suite process groups and cancel queued work before surfacing the controlled interrupt exit path.

- sequential and parallel suite interrupts both clean up child process groups
- failed-only manifests and summaries avoid partial interrupt-corrupted output
- dashboard and CLI flows share the same stricter interrupt semantics

### Plan-agent and cmux reliability fixes

The Codex plan-agent path now handles cycle aliases and starter-surface reuse more consistently.

- the `CYCLES` alias is carried through config, inspection, and queued follow-up launch paths
- headless bootstrap keeps late runtime events long enough to preserve queued plan-agent behavior
- starter-surface parsing now accepts only unique numeric `surface:<n>` handles, preventing false ambiguity when cmux repeats tokens
- planning and AI playbook docs were updated to reflect the live behavior

### Release-validation contract fixes

The repo’s canonical validation lane is now less sensitive to local workspace history and command-inventory drift.

- `pytest -q` is scoped to the repository’s authoritative `tests/` tree instead of recursing into managed historical worktrees under `trees/`
- the runtime feature inventory now includes the shipped `codex-tmux` command, keeping generated contract artifacts aligned with the actual router surface

## Included Changes

Major areas covered in this release:

- continue-task prompt provenance audit for committed divergence
- migrate action env parity with startup and saved dependency projection
- interrupt-safe cleanup for envctl-managed test suites
- Codex plan-agent cycle alias and late-event persistence fixes
- stricter cmux starter-surface parsing and duplicate-handle handling
- canonical pytest collection scoped to the repo test suite instead of managed worktree copies
- runtime feature inventory alignment for the shipped `codex-tmux` utility command
- focused docs, changelog evidence, and regression coverage across prompt, action, planning, runtime, and dashboard paths

## Operator Notes

- No data migration or manual config migration is required for this release.
- Operators using `migrate` through envctl should see fewer missing-env failures and behavior that matches runtime startup expectations.
- Teams relying on frequent `Ctrl+C` during long-running envctl test orchestration should see less leftover process cleanup work after interrupts.

## Artifacts

This release publishes:

- wheel distribution
- source distribution

After build, the artifacts are expected under `dist/`.

## Upgrade Note

If you are already using `envctl`, the most visible changes in `1.4.1` are:

- `continue_task` now asks for branch-origin divergence review before resuming work
- `migrate` inherits the backend env wiring users already expect from startup
- interrupted test runs are less likely to leave child `pytest` or `vitest` processes behind
- queued Codex planning flows behave more predictably when cycle aliases or repeated cmux surface handles are involved
- repo-local release validation no longer trips over historical worktree mirrors when running the canonical pytest lane

## Summary

`envctl` 1.4.1 makes the released workflow surface more truthful and less fragile. It focuses on prompt safety, migrate-path correctness, interrupt cleanup, and deterministic plan-agent behavior without changing the overall product model introduced in `1.4.0`.
