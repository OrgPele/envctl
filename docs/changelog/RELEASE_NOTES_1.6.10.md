# envctl 1.6.10

`envctl` 1.6.10 is a patch release on top of `1.6.9`. It ships the Ralph/OMX broad-sweep fixes and the sidebranch E2E hardening work for plan-agent launches, dry-run behavior, prompt installs, terminal UI input, path links, failed-test evidence, and lint hygiene.

## Why This Release Matters

The 1.6.x line added richer Codex, OpenCode, OMX, Ralph, Team, and ULW launch surfaces. The follow-up sweep found several places where the user experience and implementation contracts were not yet strict enough: dry-runs could still reach side-effecting startup paths, OMX/Ralph plan launches needed clearer environment control, unsupported CLI flag combinations were accepted too late, and terminal/UI helpers had edge-case regressions.

This release keeps those workflows predictable and safer by making dry-runs preview-only, validating plan-agent launch combinations before work starts, preserving actionable failure artifacts, and locking the behavior with broad regression coverage.

## Highlights

### Ralph and OMX plan launches are more predictable

- OMX/Ralph plan-agent launches can now be controlled from the envctl surface without relying on stale or sandboxed session assumptions.
- Managed plan-agent startup paths now preserve the expected OMX/Ralph workflow handoff while keeping repo/worktree context explicit.
- Unsupported `ENVCTL_PLAN_AGENT_CLI` and flag combinations fail fast before creating confusing launch state.

### Plan dry-runs are side-effect free

- explicit-selector dry-runs preview predicted plan worktrees without creating or syncing worktrees.
- interactive/no-selector dry-runs now also preview predicted plan worktrees and skip both worktree sync and plan-selection memory writes.
- startup dry-runs return after the preview instead of continuing into service/bootstrap launch orchestration.

### Codex/OpenCode/ULW launch guidance is clearer

- ULW plan launch support is reflected in the runtime feature matrix.
- plan follow-up guidance keeps multi-AI sessions isolated and avoids ambiguous reconnect instructions.
- Codex prompt installs are aligned with Codex skill compatibility expectations.

### Terminal and dashboard UX fixes

- early PTY selector keystrokes are replayed through the interactive terminal path more reliably.
- terminal hyperlink output respects automatic path-link mode instead of forcing the wrong behavior in terminals that advertise support differently.
- failed-test summaries keep the saved artifact path visible so operators can inspect the complete failure evidence instead of losing context.

### Maintenance and release hygiene

- stale F-level lint hazards were removed from the Python and test tree.
- broad runtime, planning, UI, and packaging tests were added or extended around the fixed behavior.

## Included Changes

- PR #127: OMX/Ralph managed plan launch control
- PR #128: Codex prompt install compatibility with skill-loading paths
- PR #129: runtime feature matrix coverage for ULW launch support
- PR #130: plan-agent CLI flag validation
- PR #131: failed-test/action summary artifact link preservation
- PR #132: PTY selector input replay stability
- PR #133: automatic terminal path-link mode handling
- PR #134: ruff F-level hygiene cleanup
- PR #135 / release sidebranch: E2E verification, plan dry-run startup exit, and interactive dry-run side-effect prevention

## Verification

Validated in the release worktree with:

- `PYTHONPATH=python python -m pytest -q tests/python/planning/test_planning_worktree_setup.py tests/python/runtime/test_engine_runtime_command_parity.py tests/python/runtime/test_engine_runtime_real_startup.py tests/python/planning/test_plan_agent_launch_support.py` ✅
- `PYTHONPATH=python pytest -q tests` ✅ (`1783 passed, 12 skipped, 4 warnings, 132 subtests passed`)
- `git diff --check` ✅
- `python3 -m compileall -q python tests/python` ✅
- `ruff check --select F python tests/python` ✅
- manual dry-run smokes for:
  - `envctl --plan <selector> --headless --dry-run` ✅
  - `envctl --plan <selector> --headless --dry-run --omx --ralph` ✅
  - `envctl --plan <selector> --headless --dry-run --tmux --opencode --ulw` ✅
- independent architect re-review of the previous dry-run blocker ✅

## Artifacts

This release publishes:

- wheel distribution
- source distribution
- release notes markdown asset

After build, the artifacts are available under `dist/`.

## Summary

`envctl` 1.6.10 is a Ralph/OMX reliability patch release. It makes plan dry-runs genuinely preview-only, strengthens managed plan-agent launch contracts, improves terminal/dashboard feedback, and ships the broad regression coverage needed to keep these workflows stable.
