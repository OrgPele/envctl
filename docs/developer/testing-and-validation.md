# Testing and Validation

This guide explains how the repository validates runtime behavior and what level of coverage is expected when you change the Python engine, compatibility layers, or docs.

## Test Layers

The project validates behavior across several layers:

- Python unit and integration tests under `tests/python/`
- runtime/readiness gate scripts under `scripts/`
- documentation/reference parity checks

Each layer catches different classes of failures.

## Python Tests

Python tests are the fastest way to validate:

- route parsing
- config loading
- startup/resume policy
- state model behavior
- debug bundle logic
- doctor output
- UI/backend resolution

Use these when you are changing internal Python behavior and want tight feedback loops.

## Python Integration Tests

Python integration and end-to-end tests matter when behavior is externally visible through the CLI contract.

Typical reasons to add or update this coverage:

- command routing changes
- lifecycle command behavior changes
- parity-sensitive startup behavior
- launcher and installed CLI behavior
- reference/doc surface expectations that are enforced externally

## Release and Governance Scripts

Scripts in `scripts/` act as validation tools and governance checks.

Examples:

- parity manifest generation and audit
- runtime feature matrix and gap report generation
- shipability gate checks
- debug bundle analysis helpers

If your change affects one of these machine-readable contracts, update the script-side checks too.
Script tests should assert exit status and stderr/stdout semantics, not just partial argument acceptance.

## Docs Are Part of the Contract

This repository already treats docs as part of the behavioral surface.

That means changes may require updates to:

- user guides
- reference pages
- developer guides
- README
- planning/migration docs when governance semantics change

If the runtime and docs diverge, operators and contributors both lose time.

## Minimum Expectation by Change Type

### Parser or command-surface change

Expected:

- parser tests
- dispatch/command behavior tests
- packaging or CLI smoke coverage when invocation spelling changes
- reference docs update
- release-gate/doc-parity coverage when docs or contracts are part of the command surface

### Startup/resume/runtime-truth change

Expected:

- targeted Python tests
- Python integration coverage if externally visible
- `explain-startup` or doctor validation if behavior is operator-visible
- docs update

### State or artifact contract change

Expected:

- state repository/model tests
- compatibility tests if legacy reads/writes are affected
- docs update if operators or tooling inspect the artifact

### Debug or doctor change

Expected:

- debug/runtime tests
- docs update if user-facing output or guidance changed
- governance/cutover checks if gate semantics changed

### Shell compatibility change

Expected:

- runtime readiness / release gate validation
- migration docs update if policy meaning changed

## Validation Commands

Canonical repo-wide validation:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/python -m build
.venv/bin/python scripts/release_shipability_gate.py --repo .
```

Install-path reminder:

- source-checkout operator bootstrap: `python -m pip install -r python/requirements.txt`
- contributor validation lane: `.venv/bin/python -m pip install -e '.[dev]'`

To confirm the release gate runs the same test lane:

```bash
.venv/bin/python scripts/release_shipability_gate.py --repo . --check-tests
```

Use narrower scopes while iterating, then widen before finishing. Targeted `unittest` runs remain useful for focused module work, but `pytest -q` is the authoritative repo-wide signal.

## How to Choose Test Scope

Use a narrow test scope when:

- iterating on one module
- validating a local hypothesis
- working on docs plus one small code path

Use a wider scope when:

- changing command routing
- changing startup/resume semantics
- touching compatibility or cutover logic
- changing artifacts or runtime-map shape

## Documentation Validation

At minimum, verify:

- links resolve
- examples still match the command surface
- user docs describe the primary runtime, not an outdated fallback story

For doc-heavy changes, a repository-wide markdown link check is worth running.

## Common Mistakes

- updating code without updating `explain-startup`
- changing user-visible flags without updating reference docs
- changing artifact semantics without updating doctor/debug expectations
- assuming unit tests are enough for CLI-visible behavior
- forgetting that runtime readiness and release-gate behavior still have test implications
