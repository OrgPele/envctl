# Python Runtime Gap Closure Plan

## Summary
- Generated from `contracts/python_runtime_gap_report.json`.
- Total inventoried features: 47
- Open gaps: 0
- High or medium gaps: 0

This plan keeps the current shell runtime available as a compatibility oracle while Python closes the remaining retained-behavior gaps. No shell deletion work should begin until all high and medium gaps below are closed or explicitly accepted.

## Shared Rules
- Preserve current user-visible behavior while implementing each wave.
- Keep shell-backed verification where it is still the behavior oracle.
- Mark a feature `verified_python` only after the behavior exists and the acceptance tests are in place.
- Run full Python unittest discovery and the full BATS suite after each completed wave.

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
- Full BATS suite passes.

## Follow-Up Boundary
Only after this plan is complete should a separate shell-retirement plan be executed.
