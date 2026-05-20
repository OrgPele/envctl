# envctl 1.6.4

`envctl` 1.6.4 is a patch release on top of `1.6.3`. It hardens repository test reruns, keeps dashboard failure summaries useful again, refreshes runtime inventory contracts, and smooths a few planning and terminal edge cases that were still surfacing in the Python engine.

## Why This Release Matters

`1.6.3` improved the tmux-backed planning workflow, but a few operator-facing sharp edges still remained:

- failed-only repository test reruns could still pick the wrong repo root or reintroduce wrapper-only launcher variables into nested subprocesses
- dashboard test rows could lose the saved failure excerpt even though the summary artifact still existed
- the checked-in runtime inventory and gap-report contracts could drift behind the live command surface
- some planning and terminal flows still needed better defaults or more robust output handling

This patch release focuses on those correctness issues so the Python runtime stays aligned with the actual launcher, dashboard, and contract behavior users see.

## Highlights

### Failed-only repository reruns now stay on the live checkout path

- failed-only reruns now prefer the active `RUN_REPO_ROOT` when reconstructing repository test contexts
- action subprocesses no longer inherit wrapper-only launcher overrides that can interfere with nested bare `envctl` calls
- helper test subprocesses now preserve the supplied action environment instead of silently rebuilding from ambient shell state

### Dashboard test summaries are informative again

- dashboard test rows continue to show the short summary artifact path
- failed test rows now render the saved failure excerpt consistently, including the failed test id and the key assertion detail

### Runtime contracts match the live Python command surface again

- the runtime feature matrix and gap report were regenerated from the current Python inventory
- command inventory coverage now includes the expanded Python-owned inspection and worktree helpers reflected by the router and parity tests

### Planning and terminal edge cases are steadier

- Codex tmux launches now use the intended default launch command path in planning flows
- process runner streaming tolerates malformed UTF-8 output without dropping progress or summary parsing
- interactive command recovery is more tolerant of escape-fragment noise in terminal input

## Included Changes

- live-repo failed-only rerun targeting for repository unittest suites
- wrapper-env scrubbing for action subprocesses and helper test runners
- restored dashboard failed-summary excerpt rendering
- refreshed runtime feature matrix and gap report contracts
- Codex-first plan-agent launcher defaults and tmux launch normalization
- malformed UTF-8 tolerant process output decoding and spinner fallback hardening
- release metadata updated for `1.6.4`

## Operator Notes

- rerunning `envctl test --failed --main` now reuses the current repository checkout instead of stale copied runtime state
- dashboard `tests:` rows should include the short summary path plus the saved failure excerpt when a suite is failing
- release artifacts are expected under `dist/` after building the package

## Artifacts

This release publishes:

- wheel distribution
- source distribution

After build, the artifacts are expected under `dist/`.

## Summary

`envctl` 1.6.4 is a correctness-focused patch release. It makes repository test reruns and dashboard summaries more trustworthy, keeps runtime contracts aligned with the Python command surface, and smooths a few remaining planning and terminal edge cases.
