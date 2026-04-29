# Contributing

Contributions are welcome.

This repository is Python-first at runtime. Most behavior changes therefore need two checks:

- is the Python runtime contract correct and documented?
- did the change accidentally break the supported Python runtime contract?

## Workflow
1. Create a branch from `main`.
2. Keep changes scoped to one objective.
3. Install the CLI in editable mode:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

If you are only operating `envctl` from a source checkout and are not doing contributor validation work, install the runtime-only stack with `python -m pip install -r python/requirements.txt` instead. The editable `.[dev]` lane is for contributors working on this repository itself.

4. Run the authoritative repo-wide validation lane:

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m build
.venv/bin/python scripts/release_shipability_gate.py --repo .
```

5. To verify the release gate against the same canonical test lane:

```bash
.venv/bin/python scripts/release_shipability_gate.py --repo . --check-tests
```

6. Use narrower `unittest` targets only for focused local iteration; they are no longer the authoritative release-readiness lane.

7. Use conventional commits (`type(scope): subject`).
8. Open a PR with:
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

Releases are produced by two GitHub Actions workflows:

- `.github/workflows/release-prepare.yml` (manual) bumps `pyproject.toml` and the README badges and writes `docs/changelog/RELEASE_NOTES_<version>.md` from the body of a source PR. It opens a `release/<version>` PR.
- `.github/workflows/release-publish.yml` (push to `main`) tags `v<version>`, builds the wheel + sdist, and publishes a GitHub Release using the matching release notes file.

Typical flow:

1. Merge the PR(s) you want shipped into `main`.
2. From the Actions tab, run **Release prepare**, passing the merged PR number and the bump kind (`patch` is the default; use `--version` to override).
3. Review and merge the auto-opened release PR.
4. The publish workflow will tag and ship the GitHub Release automatically.

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
