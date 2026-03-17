# envctl 1.3.2

`envctl` 1.3.2 is a hotfix release focused on command-surface correctness and release workflow polish. It adds a proper launcher-owned `--version` path, keeps installed and source-wrapper version reporting aligned, and fixes a PR-title regression in the dashboard commit/PR flow.

This release is about trust at the boundaries: the boundary between launcher and runtime, the boundary between installed and source-checkout invocation, and the boundary between the task you are implementing and the title envctl derives when it opens a PR.

## Why This Hotfix Matters

`envctl` should answer basic identity and release questions immediately.

`1.3.2` closes two places where that broke down:

- users could not ask `envctl` for its version without depending on runtime/bootstrap behavior
- dashboard PR creation could derive a bad title from a markdown subheading instead of the actual task title

## Highlights

### Launcher-owned version reporting

`envctl --version` is now a supported launcher-level flag.

- works for the installed command and for `./bin/envctl`
- does not require repo detection, `.envctl`, or runtime startup
- prefers installed package metadata and falls back to source `pyproject.toml` only when needed
- keeps runtime command inventory unchanged

### Installed/source parity and packaging coverage

The release surface now proves the version contract in the same places users hit it.

- editable-install smoke covers `envctl --version`
- regular-install smoke covers `envctl --version`
- explicit wrapper-path smoke covers `./bin/envctl --version`
- docs now treat `--version` as a normal install and troubleshooting verification step

### PR title derivation fix

Dashboard PR creation now derives titles from the task title instead of inheriting bad markdown headings.

- PR titles prefer the `MAIN_TASK.md` H1 when available
- changelog-backed commit messages skip markdown subsection headings such as `### Scope`
- the dashboard `commit` + `pr` path no longer produces PR titles like `### Scope`

## Included Changes

Major areas covered in this hotfix:

- launcher-owned `--version` support
- installed/source wrapper version parity
- packaging and launcher smoke coverage for version reporting
- install/troubleshooting/reference doc updates for `--version`
- PR-title and changelog-subject derivation hardening
- validation/docs/inventory contract alignment for the new launcher flag

## Artifacts

This release publishes:

- wheel distribution
- source distribution

After build, the artifacts are expected under `dist/`.

## Upgrade Note

If you are already using `envctl`, the most visible changes in `1.3.2` are:

- `envctl --version` now works immediately in installed and source-wrapper contexts
- install verification docs now point at `envctl --version`
- dashboard-created PRs use the task title instead of markdown subsection headings

## Summary

`envctl` 1.3.2 makes the CLI more legible and the release workflow more trustworthy. The hotfix focuses on version reporting that behaves correctly before runtime startup, and PR automation that reflects the real task title users expect.
