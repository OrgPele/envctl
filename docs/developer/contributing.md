# Contributing

Contributions are welcome.

This repository is Python-first at runtime. Most behavior changes therefore need two checks:

- is the Python runtime contract correct and documented?
- did the change accidentally break the supported Python runtime contract?

## Workflow
1. Create a branch from `dev`.
2. Keep changes scoped to one objective.
3. Install the CLI in editable mode:

```bash
uv sync --extra dev --python 3.12
```

If you are only operating `envctl` from a source checkout and are not doing contributor validation work, install the runtime-only stack with `python -m pip install -r python/requirements.txt` instead. The editable `.[dev]` lane is for contributors working on this repository itself.

4. Run the authoritative repo-wide validation lane:

```bash
uv run --extra dev pytest -q
uv run --extra dev python -m build
uv run --extra dev python scripts/release_shipability_gate.py --repo .
```

5. To verify the release gate against the same canonical test lane:

```bash
uv run --extra dev python scripts/release_shipability_gate.py --repo . --check-tests
```

6. Use narrower `unittest` targets only for focused local iteration; they are no longer the authoritative release-readiness lane.

7. Use conventional commits (`type(scope): subject`).
8. Open a PR targeting `dev` with:
- `Summary`
- `Validation`
- `Impact`

## Before Opening a PR

Confirm the change is reflected in the right doc layer:

- user docs if operators will use or notice it
- reference docs if the command, flag, or config contract changed
- developer docs if internal architecture or extension rules changed
- planning or migration docs if cutover governance meaning changed

## Documentation Changes
When behavior changes, update:
- `docs/reference/.envctl.example`
- relevant file in `docs/`
- root `README.md` (only if entrypoint/quick start changed)

## Cutting a Release

Releases are produced by `.github/workflows/release.yml`. From the Actions tab, run **Release** and pick a bump kind (`patch` is the default; pass an explicit `--version` to override). The workflow:

1. Computes the next version from `pyproject.toml`.
2. Aggregates merged PR titles since the previous version tag using GitHub's auto-generated release notes.
3. Updates `pyproject.toml`, the README badges, and writes `docs/changelog/RELEASE_NOTES_<version>.md` on a `release/envctl-<version>` branch.
4. Opens a release PR so protected `main` receives the bump through repository rules.
5. After that release PR is merged, tags the new version from `main`, builds wheel + sdist, and creates the GitHub Release.

To override GitHub's generated "What's Changed" body, check in a non-empty `docs/changelog/RELEASE_NOTES_<version>.md` file for the target version before running the release workflow. If that file is present, the workflow uses it as the release notes source; otherwise it falls back to GitHub's generated notes.

If repository policy blocks the default GitHub Actions token from creating pull requests, the workflow still pushes the `release/envctl-<version>` branch and prints a manual PR URL. Configure `ENVCTL_RELEASE_PR_TOKEN` with contents and pull-request write permissions to let the workflow open or update release PRs automatically under those policies.

If you need to dry-run the version bump locally, `python scripts/prepare_release.py compute-version --bump patch` prints the next version without modifying any files.

For Python runtime behavior changes, check whether these docs also need updates:

- `docs/user/python-engine-guide.md`
- `docs/developer/python-runtime-guide.md`
- `docs/developer/config-and-bootstrap.md`
- `docs/developer/command-surface.md`
- `docs/developer/ui-and-interaction.md`
- `docs/developer/runtime-lifecycle.md`
- `docs/developer/state-and-artifacts.md`
- `docs/developer/debug-and-diagnostics.md`
- `docs/developer/python-runtime-guide.md`
- `docs/developer/testing-and-validation.md`
