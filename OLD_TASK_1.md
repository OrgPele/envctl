# Envctl Dead Code Cleanup

## Goals / non-goals / assumptions
- Remove stale Python modules and tiny UI/test-output stubs that have no callers, while preserving all string-invoked entry points and compatibility facades.
- Add a lightweight structural contract so the same stale modules are not reintroduced silently.
- Do not refactor large orchestrators or change runtime behavior in this cleanup pass.
- Assumption: raw `rg` references and codegraph results are both needed because the live Python codegraph currently resolves only a subset of file imports.

## Goal (user experience)
Contributors should see a smaller, clearer Python engine tree: the active test-output path remains centered on `TestRunner`, parser modules, summary/progress helpers, and string-invoked pytest/unittest helpers; the UI tree keeps only modules that are imported or intentionally exposed. User-facing envctl behavior should not change.

## Business logic and data model mapping
- There is no persisted data model, migration, or runtime state format change.
- The affected surface is Python module topology under `python/envctl_engine/`.
- Test-output behavior is owned by `python/envctl_engine/test_output/test_runner.py`, `parser_base.py`, `parser_pytest.py`, `parser_jest.py`, `parser_unittest.py`, `progress_markers.py`, `summary.py`, `failure_summary.py`, and the string-invoked helpers `pytest_progress_plugin.py` and `unittest_runner.py`.
- UI selector/dashboard behavior is owned by `python/envctl_engine/ui/backend.py`, `ui/textual/screens/selector/__init__.py`, `ui/textual/screens/selector/implementation.py`, and the dashboard modules under `ui/dashboard/`.

## Current behavior (verified in code)
- Codegraph was successfully indexed after Neo4j started. Direct Cypher over `package='envctl'` found 222 engine files under `python/envctl_engine/`.
- `codegraph arch-check --json` passes all configured policies: import cycles, cross-package policy, layer bypass, coupling ceiling, and orphan detection.
- The live graph also shows limitations for this Python repo: it reports many unresolved imports, so codegraph orphan output must be cross-checked with raw references before deleting anything.
- Raw reference checks found no external references for these modules/classes/functions:
  - `python/envctl_engine/test_output/coverage.py` / `CoverageReportHandler`
  - `python/envctl_engine/test_output/error_extractor.py` / `ErrorDetailExtractor`
  - `python/envctl_engine/test_output/mode_handler.py` / `OutputModeHandler`
  - `python/envctl_engine/test_output/multi_project_runner.py` / `MultiProjectTestRunner`
  - `python/envctl_engine/ui/input_adapter.py` / `action_for_key`
  - `python/envctl_engine/ui/textual/screens/dashboard.py` / `DashboardScreenContext`
  - `python/envctl_engine/ui/textual/widgets/service_table.py` / `dashboard_snapshot_text`
- `python/envctl_engine/test_output/__init__.py` exports active symbols only: `TerminalColors`, parser classes, symbols, and `TestRunner`. It does not export the stale coverage/error/mode/multi-project modules.
- `python/envctl_engine/test_output/test_runner.py` currently handles framework detection, streaming parser callbacks, pytest progress plugin injection, unittest wrapper injection, vitest reporter injection, and summary rendering.
- `python/envctl_engine/ui/textual/screens/selector/__init__.py` intentionally imports and reexports `implementation.py`; `tests/python/ui/test_selector_package_exports.py` asserts that facade behavior. `implementation.py` is therefore not dead.
- String-invoked modules must be retained even if normal import scans mark them as low inbound:
  - `python/envctl_engine/actions/actions_cli.py`
  - `python/envctl_engine/runtime/launcher_cli.py`
  - `python/envctl_engine/runtime/cli.py`
  - `python/envctl_engine/test_output/pytest_progress_plugin.py`
  - `python/envctl_engine/test_output/unittest_runner.py`
  - `python/envctl_engine/ui/textual/selector_subprocess_entry.py`

## Root cause(s) / gaps
- The Python engine has completed major migration/refactoring work, but small helper modules from older test-output and UI designs remain after their behavior moved elsewhere.
- Existing structural tests enforce broad package layout and ownership rules, but they do not explicitly forbid stale leaf modules with no importers.
- Codegraph is helpful but insufficient as the sole dead-code authority because its Python import resolution is incomplete in this repo; implementation must use both codegraph and raw source checks.

## Plan
### 1) Reconfirm the deletion set immediately before editing
- Run `rg` for each candidate symbol before deleting:
  - `CoverageReportHandler`
  - `ErrorDetailExtractor`
  - `OutputModeHandler`
  - `MultiProjectTestRunner`
  - `action_for_key`
  - `DashboardScreenContext`
  - `dashboard_snapshot_text`
- Run scoped codegraph checks:
  - `codegraph query "MATCH (f:File {package:'envctl'}) WHERE f.path STARTS WITH 'python/envctl_engine/' RETURN count(f) AS engine_files"`
  - a scoped orphan query for `python/envctl_engine/test_output/`
  - a scoped orphan query for `python/envctl_engine/ui/`
- Treat codegraph results as candidates only; raw references are the final blocker check for this cleanup.

### 2) Delete the confirmed stale modules
- Remove:
  - `python/envctl_engine/test_output/coverage.py`
  - `python/envctl_engine/test_output/error_extractor.py`
  - `python/envctl_engine/test_output/mode_handler.py`
  - `python/envctl_engine/test_output/multi_project_runner.py`
  - `python/envctl_engine/ui/input_adapter.py`
  - `python/envctl_engine/ui/textual/screens/dashboard.py`
  - `python/envctl_engine/ui/textual/widgets/service_table.py`
- Do not delete:
  - `python/envctl_engine/ui/textual/screens/selector/implementation.py`
  - `python/envctl_engine/test_output/pytest_progress_plugin.py`
  - `python/envctl_engine/test_output/unittest_runner.py`
  - any CLI launcher/action module invoked through `python -m` or packaging entry points.

### 3) Add a structural stale-module guard
- Extend `tests/python/shared/test_structure_layout.py` or add a focused test in `tests/python/shared/` that asserts the removed files do not exist.
- Keep the guard narrow and explicit. This should prevent the known stale modules from returning, not become a general dead-code detector.
- Add comments in the test explaining that `selector/implementation.py`, `pytest_progress_plugin.py`, `unittest_runner.py`, and `selector_subprocess_entry.py` are intentional retained entry points/facades.

### 4) Preserve active test-output and selector contracts
- Do not change `python/envctl_engine/test_output/__init__.py` unless a removed module was unexpectedly exported; current evidence says it is not.
- Keep `TestRunner` behavior unchanged in `python/envctl_engine/test_output/test_runner.py`.
- Keep selector facade behavior unchanged in `python/envctl_engine/ui/textual/screens/selector/__init__.py`.
- If any import error appears after deletion, prefer fixing the stale reference or removing obsolete coverage rather than reintroducing the deleted module.

### 5) Refresh codegraph after structural deletion
- After deleting files, run `codegraph index . --since HEAD~1` from the repo root as required by `AGENTS.md`.
- Because the database contains multiple packages and some CLI stats/report commands have shown scope issues, verify with direct Cypher scoped to envctl:
  - `MATCH (f:File {package:'envctl'}) WHERE f.path STARTS WITH 'python/envctl_engine/' RETURN count(f) AS engine_files`
  - `MATCH (f:File {package:'envctl'}) WHERE f.path IN [...] RETURN f.path`
- The deleted paths should no longer appear in the live graph.

## Tests (add these)
### Backend tests
- Extend `tests/python/shared/test_structure_layout.py` with `test_removed_dead_leaf_modules_are_absent`.
- Run:
  - `PYTHONPATH=python python -m unittest tests.python.shared.test_structure_layout`
  - `PYTHONPATH=python python -m unittest tests.python.test_output.test_test_runner_streaming_fallback`
  - `PYTHONPATH=python python -m unittest tests.python.ui.test_selector_package_exports`
  - `PYTHONPATH=python python -m unittest tests.python.shared.test_import_audit`

### Frontend tests
- None. This is a Python module cleanup and does not touch frontend code.

### Integration/E2E tests
- Run `PYTHONPATH=python python -m unittest tests.python.runtime.test_cli_packaging` to confirm launcher/string-invoked module assumptions remain intact.
- Run `PYTHONPATH=python python scripts/release_shipability_gate.py --repo . --skip-build` for structural shipability.
- If a local `.venv/bin/python` exists, run the full release gate without `--skip-build`; otherwise report that the build lane is unavailable in the current checkout.

## Observability / logging
- No runtime observability changes are needed.
- The implementation should mention in the final summary that codegraph import resolution is incomplete for Python and that raw reference checks were used before deletion.

## Rollout / verification
- Recommended Codex cycles: 2.
- Rationale: this is a small multi-file static cleanup with low runtime risk, but it needs one verification/follow-up pass for tests and codegraph refresh.
- Intended launch-scope flags: `--no-infra --headless --new-session`.
- Full-stack E2E is not useful for this plan because there are no backend/frontend services, dependencies, browser-visible behavior, runtime state changes, or external integration changes; the signal is static/module tests plus codegraph refresh.
- Exact auto-launch command:
  - `ENVCTL_PLAN_AGENT_CODEX_CYCLES=2 envctl --plan refactoring/envctl-dead-code-cleanup --tmux --no-infra --headless --new-session`

## Definition of done
- The seven confirmed stale files are deleted.
- No active string-invoked entry point or selector compatibility facade is removed.
- A focused structural test prevents the deleted stale modules from returning.
- Targeted unittest scopes pass.
- `release_shipability_gate.py --repo . --skip-build` passes.
- Codegraph is refreshed after structural deletion and direct envctl-scoped Cypher confirms the deleted file nodes are absent.

## Risk register (trade-offs or missing tests)
- Risk: codegraph alone may over-report orphan functions/classes because Python import and dynamic entry point resolution are incomplete. Mitigation: every deletion must be backed by raw `rg` checks and targeted tests.
- Risk: a removed module could be imported dynamically by undocumented third-party code. Mitigation: these are internal `envctl_engine` modules not exported from public package surfaces; if compatibility is desired, keep a deprecation shim instead of deleting, but current evidence does not justify that.
- Risk: full release gate may fail in local checkouts without `.venv/bin/python`. Mitigation: run `--skip-build` for structural validation and report the environment limitation.

## Open questions
- None.
