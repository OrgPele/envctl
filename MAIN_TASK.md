# Python Runtime Gap Closure Plan

## Summary
- Generated from `contracts/python_runtime_gap_report.json`.
- Total inventoried features: 47
- Open gaps: 0
- High or medium gaps: 0

This plan records the retained-behavior gaps that had to close before shell runtime retirement. Keep these contracts green without reintroducing shell governance.

## Shared Rules
- Preserve current user-visible behavior while implementing each wave.
- Mark a feature `verified_python` only after the behavior exists and the acceptance tests are in place.
- Run full Python unittest discovery after each completed wave.

## Wave Breakdown

### Wave A: Launcher, Help, and Install Parity
Close the remaining launcher-owned and help/install gaps without changing current user-visible behavior.

No currently reported gaps in this wave.

### Wave B: Lifecycle, Planning, and Worktree Parity
Prove that lifecycle, planning, and worktree operations preserve the current behavior across startup, scale-down, and cleanup paths.

No currently reported gaps in this wave.

### Wave C: Requirements and Dependency Lifecycle Parity
Finish the risky dependency and cleanup parity areas that still make shell a compatibility oracle.

No currently reported gaps in this wave.

### Wave D: Action Command Parity
Lock down action command contracts so test/review/pr/commit/migrate no longer depend on shell-era expectations.

No currently reported gaps in this wave.

### Wave E: Diagnostics, Inspection, and Artifact Parity
Retain only the diagnostics, dashboard, and artifact behavior that is truly part of the supported product contract.

No currently reported gaps in this wave.

## Completion Gate
- All high and medium gaps are closed or explicitly accepted.
- `contracts/runtime_feature_matrix.json` is updated so closed items are marked `verified_python`.
- `contracts/python_runtime_gap_report.json` shows no remaining high or medium gaps.
- Full Python unittest discovery passes.

## Follow-Up Boundary
Shell-runtime retirement follow-up should stay mechanical and must not reintroduce shell-era governance.
