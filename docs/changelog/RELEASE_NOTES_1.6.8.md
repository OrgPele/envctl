# envctl 1.6.8

`envctl` 1.6.8 is a hotfix release on top of `1.6.7`. It trims noisy inline failed-test excerpts from the interactive dashboard so the test row stays focused on the failure artifact path and status instead of dumping individual test names directly into the dashboard snapshot.

## Why This Release Matters

The dashboard already shows the saved failure artifact path for the latest test run. Repeating the first few failed test names inline under the row adds noise without much operator value, especially for repository-wide suites.

This hotfix keeps the artifact path and status visible while removing the inline excerpt block from the dashboard tests row.

## Highlights

### Dashboard test rows are quieter

- failed test rows still show `✗ tests:` plus the saved failure artifact path
- passed test rows still show `✓ tests:` plus the saved summary path
- the dashboard no longer inlines failed test names or assertion text under the tests row

## Included Changes

- removed inline failed-test summary excerpts from dashboard tests rows
- updated dashboard rendering tests to match the quieter output
- release metadata updated for `1.6.8`

## Artifacts

This release publishes:

- wheel distribution
- source distribution
- release notes markdown asset

After build, the artifacts are expected under `dist/`.

## Summary

`envctl` 1.6.8 is a small dashboard usability hotfix. It keeps test failure paths visible while removing noisy inline failed-test excerpts from the interactive dashboard view.
