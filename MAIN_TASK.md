# Python Runtime Gap Closure Plan

## Summary
- Generated from `contracts/python_runtime_gap_report.json`.
- Total inventoried features: 46
- Open gaps: 0
- High or medium gaps: 0

Python runtime gap closure is complete. All inventoried features are marked `verified_python`, the repository is ready for shell retirement, and the next phase is the mechanical cleanup plan in `todo/plans/refactoring/shell-runtime-retirement.md`.

## Shared Rules
- Preserve current user-visible behavior while implementing each wave.
- Keep `contracts/runtime_feature_matrix.json`, `contracts/python_runtime_gap_report.json`, and this plan in sync.
- Mark a feature `verified_python` only after the behavior exists and the acceptance tests are in place.
- Validate with Python test discovery or `.venv/bin/python -m pytest -q`, plus `.venv/bin/python scripts/release_shipability_gate.py --repo .` before closing the plan.

## Wave Breakdown

### Wave A: Launcher, Help, and Install Parity
Close the remaining launcher-owned and help/install gaps without changing current user-visible behavior.

No currently reported gaps in this wave.

### Wave B: Lifecycle, Planning, and Worktree Parity
Prove that lifecycle, planning, and worktree operations preserve the current behavior across startup, scale-down, and cleanup paths.

No currently reported gaps in this wave.

### Wave C: Requirements and Dependency Lifecycle Parity
Finish the risky dependency and cleanup parity areas without regressing the Python-owned runtime contract.

No currently reported gaps in this wave.

### Wave D: Action Command Parity
Lock down action command contracts so test/review/pr/commit/migrate are fully defined by Python behavior and acceptance tests.

No currently reported gaps in this wave.

### Wave E: Diagnostics, Inspection, and Artifact Parity
Retain only the diagnostics, dashboard, and artifact behavior that is truly part of the supported product contract.

No currently reported gaps in this wave.

## Completion Gate
- All high and medium gaps are closed or explicitly accepted.
- `contracts/runtime_feature_matrix.json` is updated so closed items are marked `verified_python`.
- `contracts/python_runtime_gap_report.json` shows no remaining high or medium gaps.
- Python validation passes: `python3 -m unittest discover -s tests/python -p 'test_*.py'` or `.venv/bin/python -m pytest -q`.
- `.venv/bin/python scripts/release_shipability_gate.py --repo .` passes.

## Follow-Up Boundary
The closure gate is satisfied. Continue with `todo/plans/refactoring/shell-runtime-retirement.md` for the mechanical shell cleanup phase.
