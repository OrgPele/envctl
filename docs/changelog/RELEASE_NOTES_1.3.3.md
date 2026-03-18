# envctl 1.3.3

`envctl` 1.3.3 is a cumulative patch release on top of `1.3.2`. It includes the release-gate hotfix that made the branch shipable again, but it also carries the broader set of workflow, planning, startup, config, and dashboard improvements already present on current `main`.

This release is about making the shipped surface and the release surface line up. Since `1.3.2`, `main` picked up substantial product work: safer startup reuse, plan-agent launch support, a repo-local commit ledger, global-ignore handling for envctl-owned artifacts, and a dashboard PR dirty-worktree preflight. The immediate release blocker was the gate’s false-positive `--version` parity failure plus a stale parity manifest timestamp, but the release itself is broader than those two fixes.

## Why This Hotfix Matters

Release gates are only useful when they fail for real product issues.

`1.3.3` closes two places where the release surface was noisier than the product:

- the shipability gate could fail because docs mentioned launcher-owned `--version` while the runtime parser intentionally does not own that flag
- the checked-in parity manifest had become stale enough to trip freshness enforcement during release work

It also publishes the larger body of work that already landed on `main` after `1.3.2`.

## Highlights

### Release-gate flag parity fix

The release gate now treats `--version` the same way the parser parity tests already do: as a launcher-owned documented flag that should not be required in the runtime parser token list.

- `--version` remains documented and supported
- runtime command inventory still stays unchanged
- shipability no longer fails on a false parser/docs mismatch

### Refreshed parity manifest collateral

The checked-in parity manifest timestamp is refreshed so freshness validation reflects the current repo state instead of stale generated metadata.

- release gate freshness checks become actionable again
- no runtime command behavior changes are introduced by the manifest refresh

### Startup reuse and planning improvements

Current `main` includes broader workflow improvements beyond the release-gate fix.

- startup can safely reuse matching runs instead of rebuilding state unnecessarily
- plan execution gained cmux-backed plan-agent launch support
- shipped prompt templates now include an `implement_plan` path and updated planning guidance

### Commit, config, and dashboard workflow updates

Several day-to-day operator paths also moved forward after `1.3.2`.

- `envctl commit` now uses a repo-local `.envctl-commit-message.md` pointer ledger for default commit messages
- envctl-owned local artifacts moved from repo ignore mutation to Git global excludes management
- dashboard PR flow now detects dirty selected worktrees and offers an explicit commit/do-nothing preflight
- dashboard failed-test handling now writes one stable artifact path with cleaner failure output

## Included Changes

Major areas covered in this release:

- release-gate documented-flag parity alignment for launcher-owned `--version`
- regression coverage for the release-gate `--version` exception
- refreshed `contracts/python_engine_parity_manifest.json`
- startup run-reuse safety improvements
- cmux-backed planning and plan-agent launch support
- repo-local commit ledger defaults for `envctl commit`
- Git global excludes handling for envctl-owned local artifacts
- dashboard dirty-worktree PR confirmation flow
- dashboard failed-test artifact cleanup and quieter failure rendering
- release metadata updates for `1.3.3`

## Artifacts

This release publishes:

- wheel distribution
- source distribution

After build, the artifacts are expected under `dist/`.

## Upgrade Note

If you are already using `envctl`, the most visible changes in `1.3.3` are:

- release/readiness validation stops failing on the shipped launcher-owned `--version` contract
- startup and resume behavior are less wasteful when a compatible run already exists
- plan workflows can launch through the newer cmux-backed agent path
- default commit-message handling now comes from the repo-local envctl ledger
- dashboard PR creation handles dirty worktrees with an explicit preflight instead of forcing manual cleanup first

## Summary

`envctl` 1.3.3 fixes the release-engineering blocker that made the branch look less shipable than it really was, and it publishes the broader set of product changes already merged into `main` after `1.3.2`. The result is both a truthful release gate and a materially improved day-to-day workflow surface.
