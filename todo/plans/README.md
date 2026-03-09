# Planning Standards

This directory stores implementation plans that are executable by engineering teams and release gates.

## Required sections
Each plan must include, at minimum:
- Goal (user experience)
- Current behavior (verified in code)
- Root cause(s) / gaps
- Sequenced implementation plan
- Tests to add or extend
- Rollout / verification
- Definition of done
- Risk register

## Evidence rules
- Claims must reference concrete code paths (files and symbols).
- “Done” claims require matching automated coverage (unit and/or BATS).
- Plans that describe migration/parity work must map to release gate checks.

## Migration gate alignment
For Python-engine migration work:
- `docs/planning/python_engine_parity_manifest.json` must not overstate runtime reality.
- `docs/planning/refactoring/envctl-shell-ownership-ledger.json` status must align with shell prune budgets.
- Release gate checks in `python/envctl_engine/release_gate.py` are authoritative for shipability.

## File placement
- Keep plan files under `docs/planning/<category>/<slug>.md`.
- Categories: `broken`, `features`, `refactoring`, `implementations`.
