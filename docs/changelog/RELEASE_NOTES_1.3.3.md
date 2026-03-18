# envctl 1.3.3

`envctl` 1.3.3 is a hotfix release focused on release-surface truthfulness. It fixes a false-positive shipability failure around the launcher-owned `--version` flag and refreshes the parity manifest collateral the release gate uses for freshness enforcement.

This release is about making the release workflow say what is actually true. `--version` was already a supported launcher-level flag, but the release gate still treated it like an undocumented parser mismatch. At the same time, the parity manifest timestamp had aged out far enough to block shipability even though the runtime surface itself was still complete.

## Why This Hotfix Matters

Release gates are only useful when they fail for real product issues.

`1.3.3` closes two places where the release surface was noisier than the product:

- the shipability gate could fail because docs mentioned launcher-owned `--version` while the runtime parser intentionally does not own that flag
- the checked-in parity manifest had become stale enough to trip freshness enforcement during release work

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

## Included Changes

Major areas covered in this hotfix:

- release-gate documented-flag parity alignment for launcher-owned `--version`
- regression coverage for the release-gate `--version` exception
- refreshed `contracts/python_engine_parity_manifest.json`
- release metadata updates for `1.3.3`

## Artifacts

This release publishes:

- wheel distribution
- source distribution

After build, the artifacts are expected under `dist/`.

## Upgrade Note

If you are already using `envctl`, the most visible change in `1.3.3` is operational: release/readiness validation should stop failing on the shipped `--version` flag contract, and fresh parity collateral is included in the branch.

## Summary

`envctl` 1.3.3 is a release-engineering hotfix. It does not expand the runtime surface; it makes the shipability gate and checked-in parity artifacts accurately reflect the product behavior that was already shipped.
