# envctl 1.3.1

`envctl` 1.3.1 is a hotfix release focused on operational reliability. It closes the release-readiness and packaging gaps that remained after `1.3.0`, and it makes interactive dashboard/test behavior quieter and easier to diagnose.

This release is about confidence from a clean checkout. The tool now does a better job of bootstrapping its own test/runtime prerequisites, packaging smoke reflects the supported install path more accurately, and failed test runs preserve useful context without flooding the dashboard with duplicate output.

## Why This Hotfix Matters

`envctl` is most painful when it almost works: the build passes on a maintainer machine but not from a clean repo-local environment, or a failed dashboard test run points at an artifact path without enough context to act on quickly.

`1.3.1` addresses those operational gaps directly:

- canonical release validation now matches the documented repo-local bootstrap flow
- packaging smoke and wrapper-path behavior are more deterministic
- dashboard/test output is cleaner while still preserving actionable failure artifacts

## Highlights

### Repo-local bootstrap and validation alignment

The release/readiness workflow now consistently assumes a repo-local editable install in `.venv`.

- canonical bootstrap uses:
  - `python3.12 -m venv .venv`
  - `.venv/bin/python -m pip install -e '.[dev]'`
- shipability checks, packaging smoke, and docs are aligned to that contract
- envctl self-tests can bootstrap the repo-local env when running inside envctl repos/worktrees

### Packaging and launcher hardening

The package/install surface now better matches the way users actually invoke `envctl`.

- packaging smoke uses a build-capable interpreter and avoids local `build/` shadowing
- wrapper-path detection correctly distinguishes explicit wrapper use from shadowed bare `envctl`
- stale preserved wrapper `argv0` state no longer leaks into later launcher decisions

### Cleaner interactive dashboard/test output

Dashboard and test failures now provide signal without repeating themselves.

- failed test summaries persist compact excerpts for later inspection
- dashboard snapshot rows can show concise failure context
- failed interactive `test` runs no longer replay duplicate saved summaries
- the test summary block keeps the saved artifact path without dumping extra duplicate lines
- service rows render `log: <path>` on one line

## Included Changes

Major areas covered in this hotfix:

- release-gate and docs parity for the authoritative validation lane
- dev-extra/bootstrap packaging coverage
- envctl self-test bootstrap in repo-local `.venv`
- compact failed-test summary persistence and dashboard rendering
- interactive dashboard output cleanup
- wrapper-path and launcher-env hardening

## Artifacts

This release publishes:

- wheel distribution
- source distribution

After build, the artifacts are expected under `dist/`.

## Upgrade Note

If you are already using `envctl`, the most visible changes in `1.3.1` are:

- release/readiness checks now assume the documented repo-local `.venv` flow
- failed dashboard test runs are easier to read and less repetitive
- wrapper/install behavior is more reliable under shadowed PATH setups

## Summary

`envctl` 1.3.1 turns the `1.3.0` workflow improvements into a cleaner, more reproducible release surface. The hotfix focuses on repo-local bootstrap reliability, packaging correctness, and dashboard/test output that stays actionable without unnecessary noise.
