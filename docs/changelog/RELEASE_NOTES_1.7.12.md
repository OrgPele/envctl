# envctl 1.7.12

Today every envctl release is hand-rolled: bump `pyproject.toml`, update the README badges, write `docs/changelog/RELEASE_NOTES_<version>.md`, tag, build, and publish. This PR adds two GitHub Actions workflows (and a small helper script) that run that process from the source PR body, so the cut becomes "merge the change PR, push a button, merge the release PR."

## How it works

`scripts/prepare_release.py` exposes `compute-version` and `apply` subcommands. `apply` updates `pyproject.toml`, the three version-bound fragments in `README.md` that `tests/python/runtime/test_cli_packaging.py::test_release_version_metadata_is_consistent` already pins, and writes `docs/changelog/RELEASE_NOTES_<version>.md` from a PR body file (it injects the canonical `# envctl <version>` heading expected by `test_release_notes_exist_for_current_version` if the body doesn't already start with it).

`.github/workflows/release-prepare.yml` is a manual `workflow_dispatch`. Operators give it a merged PR number and a bump kind (`patch` default, or an explicit `--version`). It checks the PR is merged, fetches its body via `gh pr view`, runs `scripts/prepare_release.py apply`, force-pushes a `release/<version>` branch, and opens (or updates) a release PR titled `Prepare envctl <version> release`.

`.github/workflows/release-publish.yml` runs on push to `main` whenever `pyproject.toml` changes (and is also `workflow_dispatch`able). It reads the version from `pyproject.toml`, exits cleanly if `v<version>` is already tagged, otherwise verifies the matching `RELEASE_NOTES_<version>.md` exists, builds wheel + sdist with `python -m build`, tags `v<version>`, and runs `gh release create` using the notes file as the body and the built distributions as assets.

## Notes

The publish workflow needs a tag-yet-untagged version to do anything, so this PR merging will not itself trigger a release: 1.7.11 is already tagged. `docs/developer/contributing.md` gets a short `Cutting a Release` section pointing maintainers at the new flow. No changes to runtime code, packaging metadata, or existing tests; the helper script preserves the exact README/notes shape the existing release readiness tests expect.

<!-- codesmith:footer -->
---
<a href="https://app.blacksmith.sh/OrgPele/codesmith/envctl/pr/162"><picture><source media="(prefers-color-scheme: dark)" srcset="https://pr-comments-assets.blacksmith.sh/codesmith/view-in-codesmith-dark.svg"><source media="(prefers-color-scheme: light)" srcset="https://pr-comments-assets.blacksmith.sh/codesmith/view-in-codesmith-light.svg"><img alt="View in Codesmith" src="https://pr-comments-assets.blacksmith.sh/codesmith/view-in-codesmith-dark.svg"></picture></a>
<sup>Need help on this PR? Tag <code>@codesmith</code> with what you need.</sup>

- [x] Let Codesmith autofix CI failures and bot reviews
<!-- /codesmith:footer -->
