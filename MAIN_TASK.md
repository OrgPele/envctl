# Envctl Release Readiness Closure Plan

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Make the repository release-ready in a way that is reproducible from a clean repo-local environment, not only from a pre-warmed maintainer machine.
  - Align the documented validation workflow, the release gate, packaging smoke coverage, and the actual test stack so they all evaluate the same reality.
  - Eliminate the currently verified full-suite blockers: dependency-sensitive UI tests, noisy negative-path test output, and packaging/build warnings.
  - Reduce maintenance risk in the release-critical modules that currently concentrate validation, CLI, and interactive behavior.
- Non-goals:
  - Reworking unrelated product behavior in downstream target repositories.
  - Broad feature work unrelated to release readiness, packaging, validation, or the interactive/UI validation stack.
  - Replacing the Python runtime or redesigning the command surface.
- Assumptions:
  - “Release ready” for this repository means:
    - a clean repo-local bootstrap path exists and is documented,
    - the canonical full validation suite passes in that environment,
    - packaging/build smoke is clean,
    - the release gate reflects the same truth as the documented validation lane.
  - The canonical full-suite runner should move toward `pytest` for repo-wide validation because repo evidence already treats full `pytest` as the stable release-readiness signal, while narrow `unittest` runs remain useful for focused iteration.
  - Runtime dependencies (`rich`, `textual`, `prompt_toolkit`, `psutil`) remain required for the supported runtime path; tests must either provision them or skip deterministically when they are intentionally absent.

## Goal (user experience)
A contributor or release engineer should be able to clone `envctl`, follow one documented bootstrap flow, run one authoritative validation flow, and get a trustworthy answer about shipability. The repository should no longer depend on hidden local state to pass, should not emit confusing expected-failure noise during normal validation, and should build/package cleanly without deprecation warnings.

## Business logic and data model mapping
- Validation and release gate ownership:
  - `python/envctl_engine/shell/release_gate.py:evaluate_shipability`
  - `scripts/release_shipability_gate.py:main`
  - `tests/python/runtime/test_release_shipability_gate.py`
  - `tests/python/runtime/test_release_shipability_gate_cli.py`
- Packaging/installability ownership:
  - `pyproject.toml`
  - `bin/envctl`
  - `tests/python/runtime/test_cli_packaging.py`
- Contributor bootstrap and validation docs:
  - `docs/developer/contributing.md`
  - `docs/developer/testing-and-validation.md`
  - `docs/developer/python-runtime-guide.md`
  - `README.md`
- Runtime prereq and dependency behavior:
  - `python/envctl_engine/runtime/cli.py:check_prereqs`
  - `python/envctl_engine/ui/capabilities.py:textual_importable`
  - `python/envctl_engine/ui/terminal_session.py:prompt_toolkit_available`
- Interactive selector/test behavior:
  - `python/envctl_engine/ui/textual/screens/selector/textual_impl.py:run_textual_selector`
  - `python/envctl_engine/ui/textual/screens/selector/__init__.py:_run_textual_selector`
  - `python/envctl_engine/ui/prompt_toolkit_list.py:create_prompt_toolkit_tty_io`
  - `python/envctl_engine/ui/prompt_toolkit_cursor_menu.py:_create_prompt_toolkit_tty_io`
  - `python/envctl_engine/ui/textual/screens/selector/prompt_toolkit_impl.py:_create_prompt_toolkit_tty_io`
- Validation-tool bootstrap behavior:
  - `scripts/python_cleanup.py:_ensure_python_modules_available`
  - `tests/python/shared/test_python_cleanup_script.py`
- Maintainability guardrails:
  - `tests/python/shared/test_import_audit.py`
  - release-critical hotspots currently concentrated in:
    - `python/envctl_engine/runtime/engine_runtime.py`
    - `python/envctl_engine/actions/action_command_orchestrator.py`
    - `python/envctl_engine/actions/project_action_domain.py`
    - `python/envctl_engine/ui/terminal_session.py`
    - `python/envctl_engine/runtime/command_router.py`

## Current behavior (verified in code)
- The release gate and the docs are not using one consistent validation contract:
  - `docs/developer/contributing.md` and `docs/developer/testing-and-validation.md` still present `.venv/bin/python -m unittest discover -s tests/python -p 'test_*.py'` as the canonical repo-wide check.
  - `docs/developer/python-runtime-guide.md` states that direct module execution from repo root requires `PYTHONPATH=python`.
  - `python/envctl_engine/shell/release_gate.py:evaluate_shipability` runs `.venv/bin/python -m unittest discover -s tests/python -p test_*.py` when `check_tests=True`.
  - `docs/changelog/main_changelog.md` already records that raw `python -m unittest discover ...` is noisy for unattended repo-wide validation and that the full `pytest` suite is the reliable regression signal.
- The current full-suite behavior is dependency-sensitive and inconsistent across UI tests:
  - `python/envctl_engine/ui/textual/screens/selector/textual_impl.py:run_textual_selector` returns `None` when `textual` is unavailable.
  - `tests/python/ui/test_textual_selector_responsiveness.py` calls `selector._run_textual_selector(... build_only=True)` and assumes the returned app is non-`None` in multiple tests.
  - `tests/python/ui/test_textual_selector_interaction.py` patches `prompt_toolkit.input.defaults.create_input` and `prompt_toolkit.output.defaults.create_output` directly, which raises `ModuleNotFoundError` when `prompt_toolkit` is not installed.
  - Other UI tests already use explicit `skipTest(...)` guards when Textual or prompt_toolkit is absent (`tests/python/ui/test_pr_flow.py`, `tests/python/ui/test_text_input_dialog.py`, `tests/python/ui/test_interactive_selector_key_throughput_pty.py`), so the test policy is inconsistent.
- Validation output is noisier than it should be for expected negative-path coverage:
  - `tests/python/runtime/test_command_exit_codes.py` intentionally exercises invalid route tokens like `tees=true` and missing dependency behavior from `python/envctl_engine/runtime/cli.py:check_prereqs`, which prints user-facing error text.
  - `tests/python/shared/test_python_cleanup_script.py` intentionally exercises `scripts/python_cleanup.py:parse_args` error paths.
  - `python/envctl_engine/ui/command_loop.py` and fallback menu paths print interactive prompts and status text during certain tests unless explicitly captured.
- Packaging/installability coverage is useful but incomplete for release readiness:
  - `tests/python/runtime/test_cli_packaging.py` verifies wrapper behavior and editable/non-editable installability, but installs with `--no-deps --no-build-isolation`, so it does not prove that the runtime dependency set is present in the packaged environment.
  - `pyproject.toml` still uses `[tool.setuptools].license-files`, which emitted a Setuptools deprecation warning during `python3 -m build`.
- Validation tool bootstrap is under-documented:
  - `scripts/python_cleanup.py:_ensure_python_modules_available` requires `ruff`, `basedpyright`, and `vulture`.
  - The primary contributor/testing docs do not document a supported bootstrap path for those validation tools.
- Release-critical behavior is concentrated in large modules, increasing regression risk when closing readiness gaps:
  - verified file sizes include `python/envctl_engine/actions/action_command_orchestrator.py` (~1782 lines), `python/envctl_engine/runtime/engine_runtime.py` (~1633 lines), `python/envctl_engine/ui/terminal_session.py` (~1063 lines), `python/envctl_engine/actions/project_action_domain.py` (~1086 lines), and `python/envctl_engine/runtime/command_router.py` (~986 lines).

## Root cause(s) / gaps
- No single authoritative validation lane exists across docs, release gating, and packaging smoke; each surface checks a different subset of reality.
- The repository assumes an implicitly prepared local environment:
  - runtime dependencies are required for many flows,
  - validation-tool dependencies are required for cleanup/lint workflows,
  - but the primary docs do not define a single supported bootstrap contract for both.
- UI tests mix two incompatible strategies:
  - “runtime deps must be installed” and
  - “skip when optional deps are absent.”
  This leaves the full suite brittle outside a maintainer venv.
- Some tests assert user-facing error behavior without capturing the expected stderr/stdout, which makes full-suite output noisy and masks real failures.
- Packaging/release checks currently under-enforce cleanliness:
  - build warnings are not treated as a release-readiness problem,
  - install smoke does not verify dependency-complete runtime behavior,
  - `check_tests=True` in the release gate does not necessarily run the same suite contributors are told to trust.
- The highest-risk release-critical modules are too large, so small readiness fixes are more likely to introduce regressions and harder to review with confidence.

## Plan
### 1) Establish one authoritative release-validation contract
- Choose and document one canonical repo-wide validation lane, then align all release-facing surfaces to it.
- Recommended contract:
  - bootstrap: create repo-local `.venv`, install package in editable mode with a documented validation toolset,
  - full suite: `pytest -q` (repo-wide),
  - packaging: `python -m build`,
  - release gate: `python scripts/release_shipability_gate.py --repo .` plus a test-enabled variant that runs the same canonical suite.
- Update these files together so they cannot drift again:
  - `docs/developer/contributing.md`
  - `docs/developer/testing-and-validation.md`
  - `docs/developer/python-runtime-guide.md`
  - `README.md`
  - `python/envctl_engine/shell/release_gate.py`
  - `scripts/release_shipability_gate.py`
- Implementation detail:
  - keep targeted `unittest` examples only for narrow local iteration and explicitly label them as non-authoritative for release readiness.

### 2) Define and ship a supported developer/bootstrap dependency contract
- Add a first-class bootstrap surface for repo contributors and release validation.
- Recommended path:
  - add either `project.optional-dependencies.dev` in `pyproject.toml` or a dedicated `requirements-dev.txt`/`python/dev-requirements.txt`,
  - include at minimum: `pytest`, `ruff`, `basedpyright`, `vulture`, and any repo-required test/runtime helpers,
  - keep runtime dependencies (`rich`, `textual`, `prompt_toolkit`, `psutil`) in the normal package install path.
- Update `tests/python/runtime/test_cli_packaging.py` so packaging smoke covers:
  - editable install with dependencies,
  - non-editable install with dependencies,
  - at least one command path that proves runtime dependencies are truly present.
- Keep `scripts/python_cleanup.py` aligned with the same bootstrap contract so its install hint matches the documented setup.

### 3) Make UI and selector tests dependency-safe and deterministic
- Standardize one policy for dependency-sensitive UI tests:
  - if a test verifies runtime behavior that truly requires Textual or prompt_toolkit, the test environment must install them,
  - if a test is intentionally validating fallback behavior without those dependencies, it must inject stubs or skip explicitly rather than fail at import-time patch resolution.
- Update and normalize these test files:
  - `tests/python/ui/test_textual_selector_responsiveness.py`
  - `tests/python/ui/test_textual_selector_interaction.py`
  - `tests/python/ui/test_pr_flow.py`
  - `tests/python/ui/test_text_input_dialog.py`
  - `tests/python/ui/test_interactive_selector_key_throughput_pty.py`
  - `tests/python/ui/test_prompt_toolkit_cursor_menu.py`
  - `tests/python/ui/test_prompt_toolkit_selector_shared_behavior.py`
- If needed, adjust runtime helpers to expose clearer preconditions:
  - `python/envctl_engine/ui/textual/screens/selector/textual_impl.py`
  - `python/envctl_engine/ui/capabilities.py`
  - `python/envctl_engine/ui/terminal_session.py`
- Required edge cases:
  - `build_only=True` selector construction when `textual` is unavailable,
  - direct patching of `prompt_toolkit.*` paths when the package is absent,
  - PTY tests that should skip in unsupported environments instead of failing late.

### 4) Eliminate expected-failure noise from the repo-wide suite
- Audit negative-path tests and make them capture the stderr/stdout they intentionally provoke.
- Target files first:
  - `tests/python/runtime/test_command_exit_codes.py`
  - `tests/python/runtime/test_cli_router.py`
  - `tests/python/shared/test_python_cleanup_script.py`
  - `tests/python/ui/test_ui_menu_interactive.py`
  - any other test files that intentionally exercise CLI parse failures, prereq failures, or fallback menu prompts.
- Keep the product behavior user-facing and unchanged where appropriate; the cleanup is primarily in tests and harnesses.
- Add a regression check that the canonical full-suite command produces no unexpected usage banners or interactive prompt spam unless the test explicitly asserts that output.

### 5) Harden packaging and shipability checks so they cover the real release surface
- Update `pyproject.toml` to remove the deprecated setuptools configuration and keep builds warning-free.
- Extend packaging smoke to assert:
  - wheel/sdist build succeeds,
  - editable install still works,
  - regular install still works,
  - dependency-complete runtime smoke succeeds.
- Expand release-gate coverage so it can optionally fail on packaging/build hygiene problems, not only runtime-readiness contract issues.
- Reconcile `python/envctl_engine/shell/release_gate.py:evaluate_shipability(check_tests=True)` with the new canonical validation lane so “check tests” means the same thing everywhere.
- Ensure related docs and tests are updated together:
  - `tests/python/runtime/test_release_shipability_gate.py`
  - `tests/python/runtime/test_release_shipability_gate_cli.py`
  - `tests/python/runtime/test_cli_packaging.py`

### 6) Add explicit docs-and-tools parity checks for validation workflow drift
- Add machine-checked coverage that keeps docs, scripts, and contributor instructions aligned.
- Recommended additions:
  - a test that asserts the documented bootstrap command, canonical full-suite command, and release-gate test command remain in sync,
  - a test that asserts developer docs mention direct-module `PYTHONPATH=python` requirements only where still necessary,
  - a test that asserts `python_cleanup.py` prerequisites are documented wherever that tool is presented as supported workflow.
- Primary files to cover:
  - `docs/developer/contributing.md`
  - `docs/developer/testing-and-validation.md`
  - `docs/developer/python-runtime-guide.md`
  - `scripts/python_cleanup.py`
  - `python/envctl_engine/shell/release_gate.py`

### 7) Decompose release-critical hot spots once the validation lane is green
- After the suite, packaging, and release gates are stable, extract the highest-risk logic from the current hotspot files into smaller policy modules with dedicated tests.
- Prioritize modules that directly affect release readiness:
  - `python/envctl_engine/ui/terminal_session.py`
    - extract raw-byte read/pushback, escape-sequence handling, and terminal restore policy into smaller helpers.
  - `python/envctl_engine/runtime/command_router.py`
    - extract flag tables, env-style assignment handling, and alias validation into table-driven policy helpers.
  - `python/envctl_engine/runtime/cli.py`
    - extract prereq policy, bootstrap gating, and exit-code normalization into focused helpers.
  - `python/envctl_engine/actions/action_command_orchestrator.py`
  - `python/envctl_engine/actions/project_action_domain.py`
    - extract command-family policy and artifact/reporting helpers so release-related fixes stop landing in 1000+ line files.
- Use `tests/python/shared/test_import_audit.py` to add ownership rules for newly extracted helpers so the refactor remains stable.
- Keep this phase sequenced after correctness closure; do not combine the large-file decomposition with the initial release-readiness fixes in one implementation slice.

### 8) Documentation and changelog closure
- When implementation lands, append a changelog entry describing:
  - the new authoritative validation lane,
  - dependency/bootstrap expectations,
  - packaging/build hygiene improvements,
  - any new release-gate semantics.
- Update docs so the repo no longer sends contributors through contradictory validation paths.

## Tests (add these)
### Backend tests
- Extend `tests/python/runtime/test_cli_packaging.py`:
  - editable install with dependencies exposes `envctl --help`,
  - regular install with dependencies supports `doctor --repo`,
  - packaging build smoke succeeds with no deprecated config use.
- Extend `tests/python/runtime/test_release_shipability_gate.py`:
  - `check_tests=True` uses the authoritative validation command,
  - packaging/build failures surface as shipability failures or explicit warnings, depending on policy.
- Extend `tests/python/runtime/test_release_shipability_gate_cli.py`:
  - CLI output explicitly reports which validation lane ran,
  - test-enabled gate failures remain actionable and quiet.
- Extend `tests/python/shared/test_python_cleanup_script.py`:
  - install hints align with the chosen bootstrap contract,
  - report-only mode stays quiet unless explicitly expected.
- Add a docs/tools parity test, for example `tests/python/shared/test_validation_workflow_contract.py`:
  - docs, release gate, and bootstrap guidance stay aligned.

### Frontend tests
- Extend `tests/python/ui/test_textual_selector_responsiveness.py`:
  - explicit skip or stub path when Textual is absent,
  - `build_only=True` selector-app construction contract is deterministic.
- Extend `tests/python/ui/test_textual_selector_interaction.py`:
  - prompt_toolkit I/O tests do not fail at import resolution when prompt_toolkit is absent,
  - selector backend selection behavior remains covered under both installed and missing-dependency conditions.
- Extend `tests/python/ui/test_pr_flow.py`, `tests/python/ui/test_text_input_dialog.py`, and `tests/python/ui/test_interactive_selector_key_throughput_pty.py`:
  - availability checks remain explicit and consistent.
- Add a focused dependency-contract test, for example `tests/python/ui/test_ui_dependency_contract.py`:
  - `textual_importable()` and `prompt_toolkit_available()` behavior is consistent with the test suite’s skip/stub policy.

### Integration/E2E tests
- Add a fresh-venv validation smoke lane, either as:
  - a new packaging/release smoke test module, or
  - an extended `tests/python/runtime/test_cli_packaging.py` scenario,
  that provisions the documented bootstrap contract and runs the canonical validation command in that isolated environment.
- Add a release workflow smoke test that exercises:
  - bootstrap,
  - full suite,
  - `python -m build`,
  - `scripts/release_shipability_gate.py --repo .`,
  using the same documented order the release docs recommend.
- If CI cost is too high for every PR, keep this smoke lane in release/nightly CI but make the contract testable locally and document the exact job.

## Observability / logging (if relevant)
- When `check_tests=True` or packaging/build checks are enabled in the release gate, print the exact validation command and the failing stage so release failures are diagnosable without reading implementation code.
- If packaging/build hygiene becomes part of shipability, include distinct error classes such as:
  - `packaging_build_failed`
  - `packaging_build_warned`
  - `validation_lane_failed`
  - `validation_lane_misconfigured`
- Keep these messages short and user-facing; the repo does not need heavy new telemetry for this slice.

## Rollout / verification
- Phase A: validation-contract alignment
  - finalize canonical bootstrap and full-suite commands,
  - update docs and release gate together.
- Phase B: dependency/bootstrap cleanup
  - add dev/validation dependency surface,
  - update packaging smoke accordingly.
- Phase C: UI test stabilization
  - normalize skip/stub policy across Textual and prompt_toolkit tests,
  - make full repo-wide validation quiet and deterministic.
- Phase D: packaging and gate hardening
  - remove deprecated setuptools config,
  - add build smoke and release-gate packaging coverage.
- Phase E: maintainability follow-through
  - extract helpers from hotspot modules with import-audit ownership rules.
- Verification checklist:
  1. Fresh repo-local `.venv` bootstrap follows the documented steps exactly.
  2. The canonical repo-wide validation command passes in that environment.
  3. `python -m build` completes without setuptools deprecation warnings.
  4. `python scripts/release_shipability_gate.py --repo .` reflects the same truth as the documented validation lane.
  5. Full-suite output no longer includes stray expected-failure usage banners or interactive prompt spam.
  6. Dependency-sensitive UI tests either run because dependencies are installed or skip explicitly and deterministically for the documented reason.
  7. `docs/changelog/main_changelog.md` is updated when implementation lands.

## Definition of done
- The repository has one documented, authoritative bootstrap and release-validation workflow.
- The canonical repo-wide validation suite passes in a clean repo-local environment without relying on hidden local setup.
- Packaging/build smoke is clean and warning-free.
- Release-gate test mode runs the same validation lane contributors and release engineers are told to trust.
- UI/selector tests no longer fail unpredictably when Textual or prompt_toolkit are unavailable; the suite’s policy is explicit and enforced.
- Expected negative-path CLI behavior remains covered, but the repo-wide test run output is quiet enough that real failures are obvious.
- The first round of release-critical module decomposition is planned and guarded so future readiness fixes stop landing in oversized files.

## Risk register (trade-offs or missing tests)
- Risk: standardizing on a dependency-complete bootstrap path will lengthen local setup time.
  - Mitigation: keep a narrow “fast iteration” lane documented separately from the release-authoritative lane.
- Risk: adding packaging/build cleanliness checks to shipability may initially fail frequently on maintainers’ machines.
  - Mitigation: roll the check in with clear stage-by-stage failure messages and fix the bootstrap/docs first.
- Risk: UI dependency tests can still be flaky if they mix real PTY behavior with availability probing.
  - Mitigation: separate “dependency present” tests from “dependency absent fallback” tests and keep each deterministic.
- Risk: decomposing hotspot modules alongside release fixes could expand scope too far.
  - Mitigation: sequence the large-file refactors after the validation lane is green and gate them with focused ownership tests.

## Open questions (only if unavoidable)
- None. The plan resolves the current scope from repo evidence and treats “full pytest suite as the authoritative repo-wide validation lane” as an explicit assumption to implement and document.
