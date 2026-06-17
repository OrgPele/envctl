# Testing and Validation

This guide explains how the repository validates runtime behavior and what level of coverage is expected when you change the Python engine, compatibility layers, or docs.

## Test Layers

The project validates behavior across several layers:

- Python unit and integration tests under `tests/python/`
- runtime/readiness gate scripts under `scripts/`
- documentation/reference parity checks

Each layer catches different classes of failures.

## Test Suite Taxonomy

Use the smallest test layer that protects the behavior contract you are changing:

- Unit tests: pure functions, value objects, planners, parsers, and policy decisions with no process, Git, or filesystem orchestration beyond a temporary directory.
- Contract tests: stable public or cross-module behavior such as command payloads, state artifacts, release-gate inputs, runtime feature matrices, and documented output semantics.
- Parity tests: migration or facade equivalence checks where an older route and a newer owner must remain behaviorally identical. Keep one clear test per behavior and prefer parametrized cases over copied methods.
- Integration tests: CLI dispatch, subprocess boundaries, Git or GitHub workflow orchestration, installed-entrypoint behavior, and runtime startup flows that need multiple components together.
- Runtime startup tests: startup, resume, service bootstrap, dependency readiness, and process cleanup behavior. Keep these under `tests/python/startup` or `tests/python/runtime` depending on whether the assertion is about startup orchestration or lower-level runtime primitives.
- UI tests: dashboard, textual selector, config wizard, and rendering contracts under `tests/python/ui` or the matching textual/config domain when the owner is more specific.
- Packaging tests: installed CLI, package data, build metadata, and entrypoint expectations under runtime packaging coverage.
- Release-gate tests: shipability, generated matrices, gap reports, and governance scripts. These must preserve the machine-readable contract used by release automation.

When a test file grows because it is covering several of these categories, split by behavior owner rather than by line count alone. Shared helpers belong in `*_test_support.py` only when they remove real duplication across multiple files; otherwise keep setup local so the test remains readable.

Prefer parametrized cases when the same behavior is being checked against many inputs. Prefer a new file when the setup, owner module, or failure meaning changes.

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
uv sync --extra dev --python 3.12
uv run --extra dev pytest -q
uv run --extra dev python -m build
uv run --extra dev python scripts/release_shipability_gate.py --repo .
```

Install-path reminder:

- source-checkout operator bootstrap: `python -m pip install -r python/requirements.txt`
- contributor validation lane: `uv sync --extra dev --python 3.12`

To confirm the release gate runs the same test lane:

```bash
uv run --extra dev python scripts/release_shipability_gate.py --repo . --check-tests
```

The canonical PR CI lane is:

```bash
uv run --extra dev pytest -q -n 4 --dist=loadscope --maxfail=25 --ff --junitxml=test-results/junit.xml
```

`--dist=loadscope` keeps tests from the same module or class on the same worker, which reduces fixture churn and keeps failure ordering easier to interpret while still running the suite in parallel.

For an inventory of suite size, helpers, markers, skipped or slow tests, and duplicate test-name clusters:

```bash
uv run --extra dev python scripts/test_suite_inventory.py --repo .
uv run --extra dev python scripts/test_suite_inventory.py --repo . --json
```

Use `--check` with thresholds for cleanup planning or a local guardrail, for example:

```bash
uv run --extra dev python scripts/test_suite_inventory.py --repo . --check --max-file-lines 1200
```

Serena is the repo's symbolic code navigation tool. It is configured by `.serena/project.yml` and should be used for
architecture discovery, dependency tracing, and refactor planning when available:

```bash
serena project health-check
```

Serena is not a CI gate for this repository. Keep CI-style validation centered on pytest, ruff, build, and the release
shipability gate. Use Serena as an interactive symbol/reference layer before broad text search.

CodeGraphContext (`cgc`) is the repo-wide graph analysis layer for ownership, coupling, impact, and hotspot questions.
Use `cgc` commands such as `cgc stats --context Envctl`, `cgc report --context Envctl`, and read-only `cgc query ...`
when the question crosses many modules. Do not use the legacy `codegraph` CLI or `.codegraph/` indexes in envctl.
Use `rg` for exact strings such as flags, log messages, config keys, and docs prose.

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
