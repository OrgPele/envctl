## 2026-03-16 - Align release-readiness validation, packaging smoke, and dependency-safe UI tests

- Scope:
  - Established one authoritative contributor/release validation contract around a repo-local `.venv`, editable install with `.[dev]`, `pytest -q`, `python -m build`, and the release shipability gate.
  - Hardened release-gate behavior so packaging/build smoke and the canonical test lane can be checked from the same command surface.
  - Made dependency-sensitive UI tests deterministic when `textual` or `prompt_toolkit` are absent instead of depending on a pre-warmed maintainer environment.

- Key behavior changes:
  - `python/envctl_engine/shell/release_gate.py`
    - Added canonical bootstrap/validation/build command constants.
    - `check_tests=True` now runs the canonical repo-local `pytest -q` lane instead of repo-wide `unittest discover`.
    - Added optional packaging/build checking with actionable stage errors:
      - `validation_lane_failed`
      - `validation_lane_misconfigured`
      - `packaging_build_failed`
      - `packaging_build_misconfigured`
      - `packaging_build_warned`
    - Normalized command rendering so the CLI reports `.venv/bin/python ...` consistently.
  - `scripts/release_shipability_gate.py`
    - Default gate now reports and runs packaging build smoke unless `--skip-build` is passed.
    - `--check-tests` now reports the canonical validation lane before execution.
  - `pyproject.toml`
    - Added `project.optional-dependencies.dev` for repo validation tooling (`pytest`, `build`, `ruff`, `basedpyright`, `vulture`).
    - Moved `license-files` to PEP 621 project metadata so `python -m build` no longer emits the setuptools deprecation warning.
  - `scripts/python_cleanup.py`
    - Missing-tool bootstrap guidance now points contributors at `.venv/bin/python -m pip install -e '.[dev]'`.
  - Docs (`README.md`, `docs/developer/contributing.md`, `docs/developer/testing-and-validation.md`, `docs/developer/python-runtime-guide.md`)
    - Updated to the same bootstrap, validation, build, and release-gate workflow.
    - Kept `PYTHONPATH=python` guidance only in the runtime guide where direct module execution is actually discussed.
  - Packaging/test coverage
    - Added doc/tool parity tests.
    - Extended packaging smoke to verify dev-extra metadata, warning-free builds, editable/non-editable installability, and offline dependency-complete runtime imports.
    - Added UI dependency-contract tests and explicit skip/stub behavior for missing `textual` and `prompt_toolkit`.
    - Reduced noisy expected-failure test output by capturing intentional stderr/stdout in targeted negative-path tests.

- Files/modules touched:
  - `README.md`
  - `docs/developer/contributing.md`
  - `docs/developer/python-runtime-guide.md`
  - `docs/developer/testing-and-validation.md`
  - `docs/changelog/main_changelog.md`
  - `pyproject.toml`
  - `python/envctl_engine/shell/release_gate.py`
  - `scripts/python_cleanup.py`
  - `scripts/release_shipability_gate.py`
  - `tests/python/runtime/test_cli_packaging.py`
  - `tests/python/runtime/test_command_exit_codes.py`
  - `tests/python/runtime/test_release_shipability_gate.py`
  - `tests/python/runtime/test_release_shipability_gate_cli.py`
  - `tests/python/shared/test_python_cleanup_script.py`
  - `tests/python/shared/test_validation_workflow_contract.py`
  - `tests/python/ui/test_prompt_toolkit_cursor_menu.py`
  - `tests/python/ui/test_prompt_toolkit_selector_shared_behavior.py`
  - `tests/python/ui/test_textual_selector_interaction.py`
  - `tests/python/ui/test_textual_selector_responsiveness.py`
  - `tests/python/ui/test_ui_dependency_contract.py`
  - `tests/python/ui/test_ui_menu_interactive.py`

- Tests run + results:
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_release_shipability_gate tests.python.runtime.test_release_shipability_gate_cli tests.python.runtime.test_cli_packaging tests.python.shared.test_validation_workflow_contract tests.python.shared.test_python_cleanup_script tests.python.runtime.test_command_exit_codes tests.python.ui.test_ui_menu_interactive tests.python.ui.test_ui_dependency_contract tests.python.ui.test_textual_selector_responsiveness tests.python.ui.test_textual_selector_interaction tests.python.ui.test_prompt_toolkit_cursor_menu tests.python.ui.test_prompt_toolkit_selector_shared_behavior`
    - Result: pass (`Ran 146 tests in 15.292s`, `OK`, `25 skipped` for dependency-absent UI environments).

- Config/env/migrations:
  - Added `project.optional-dependencies.dev` as the supported repo-local validation bootstrap surface.
  - No new runtime config keys or environment variables.
  - No state/data migrations.

- Risks/notes:
  - The release gate’s canonical packaging/test lanes now intentionally require a repo-local `.venv/bin/python`; structure-only iteration can use `--skip-build` and/or `--skip-tests`.
  - Packaging warning detection currently keys off warning/deprecation lines in build output; if upstream tooling changes its warning format, this may need a small follow-up adjustment.

## 2026-03-16 - Fix release-readiness regression tests on Python 3.12 and dep-light environments

- Scope:
  - Stabilized the follow-up regression suite after the first release-readiness implementation uncovered Python 3.12 packaging harness assumptions and dependency-availability mismatches in PTY/Textual tests.

- Key behavior changes:
  - `tests/python/runtime/test_cli_packaging.py`
    - Packaging smoke now selects an available interpreter that actually has `setuptools` and `build`.
    - Build invocations use `-P` so a local repo `build/` directory cannot shadow the `build` frontend module.
    - Temporary install envs are created from that packaging-capable interpreter, making editable and non-editable install smoke deterministic under Python 3.12.
  - `tests/python/ui/test_textual_selector_responsiveness.py`
    - The Textual-absent regression now patches the real import point used by `run_textual_selector`.
  - `tests/python/ui/test_interactive_selector_key_throughput_pty.py`
    - Default-Textual PTY tests now skip explicitly when `textual` is absent instead of assuming `prompt_toolkit` availability is sufficient.
  - `tests/python/startup/test_startup_spinner_integration.py`
    - Hardened tempdir cleanup in the spinner lifecycle test to tolerate delayed legacy-runtime cleanup.

- Files/modules touched:
  - `tests/python/runtime/test_cli_packaging.py`
  - `tests/python/startup/test_startup_spinner_integration.py`
  - `tests/python/ui/test_interactive_selector_key_throughput_pty.py`
  - `tests/python/ui/test_textual_selector_responsiveness.py`

- Tests run + results:
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_cli_packaging tests.python.ui.test_textual_selector_responsiveness tests.python.startup.test_startup_spinner_integration tests.python.ui.test_interactive_selector_key_throughput_pty`
    - Result: pass (`Ran 59 tests in 15.085s`, `OK`, `24 skipped`).
  - `PYTHONPATH=python python3 -m unittest tests.python.runtime.test_release_shipability_gate tests.python.runtime.test_release_shipability_gate_cli tests.python.runtime.test_cli_packaging tests.python.shared.test_validation_workflow_contract tests.python.shared.test_python_cleanup_script tests.python.runtime.test_command_exit_codes tests.python.ui.test_ui_menu_interactive tests.python.ui.test_ui_dependency_contract tests.python.ui.test_textual_selector_responsiveness tests.python.ui.test_textual_selector_interaction tests.python.ui.test_prompt_toolkit_cursor_menu tests.python.ui.test_prompt_toolkit_selector_shared_behavior tests.python.startup.test_startup_spinner_integration tests.python.ui.test_interactive_selector_key_throughput_pty`
    - Result: pass (`Ran 157 tests in 16.331s`, `OK`, `31 skipped`).

- Config/env/migrations:
  - No new config/env keys.
  - No state/data migrations.

- Risks/notes:
  - Packaging smoke now intentionally prefers an interpreter with both `setuptools` and `build`; if none is available locally, those tests skip rather than fail for an irrelevant host-tooling reason.

## 2026-03-16 - Bootstrap envctl test prerequisites and surface failure excerpts in dashboard mode

- Scope:
  - Investigated why interactive dashboard test failures only propagated a saved `ft_*.txt` path with little inline context.
  - Added repo-local env bootstrap for envctl test actions so worktree-local runs stop depending on the interpreter that launched the parent session.
  - Surfaced compact failure excerpts everywhere the saved test summary is rendered or replayed.

- Key behavior changes:
  - Test bootstrap:
    - `python/envctl_engine/actions/actions_test.py`
      - Added `ensure_repo_local_test_prereqs(...)` for envctl repositories/worktrees.
      - Detects the envctl repo contract from `pyproject.toml` + `python/envctl_engine`.
      - Creates `.venv` when absent and installs `-e '.[dev]'` when the repo-local interpreter is missing the expected runtime/test packages.
      - Produces an actionable bootstrap failure message with the exact remediation commands.
    - `python/envctl_engine/actions/action_test_runner.py`
      - Runs the repo-local bootstrap preflight once per selected project root before building test execution specs.
  - Failure-context surfacing:
    - `python/envctl_engine/test_output/failure_summary.py`
      - New shared helper that extracts compact, high-signal summary lines from saved failed-test summaries or persisted metadata.
    - `python/envctl_engine/actions/action_command_orchestrator.py`
      - Persists `summary_excerpt` alongside saved test-summary metadata.
      - Prints excerpt lines inside the main `Test Suite Summary` block before the saved summary path.
    - `python/envctl_engine/ui/dashboard/rendering.py`
      - Dashboard test rows now render excerpt lines under a failed test status instead of only the artifact path.
    - `python/envctl_engine/ui/dashboard/orchestrator.py`
      - Interactive dashboard failures now replay a compact `Test failure summary for <project>` block from saved metadata.
  - CLI prereq guidance:
    - `python/envctl_engine/runtime/cli.py`
      - Missing-runtime-package errors now point to the canonical bootstrap flow:
        - `python3.12 -m venv .venv`
        - `.venv/bin/python -m pip install -e '.[dev]'`

- Files/modules touched:
  - `python/envctl_engine/actions/action_command_orchestrator.py`
  - `python/envctl_engine/actions/action_test_runner.py`
  - `python/envctl_engine/actions/actions_test.py`
  - `python/envctl_engine/runtime/cli.py`
  - `python/envctl_engine/test_output/failure_summary.py`
  - `python/envctl_engine/ui/dashboard/orchestrator.py`
  - `python/envctl_engine/ui/dashboard/rendering.py`
  - `tests/python/actions/test_actions_parity.py`
  - `tests/python/runtime/test_prereq_policy.py`
  - `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`
  - `tests/python/ui/test_dashboard_rendering_parity.py`

- Tests run + results:
  - `PYTHONPATH=python .venv/bin/python -m unittest tests.python.runtime.test_prereq_policy`
    - Result: pass (`Ran 3 tests`, `OK`).
  - `PYTHONPATH=python .venv/bin/python -m unittest tests.python.ui.test_dashboard_rendering_parity`
    - Result: pass (`Ran 13 tests`, `OK`).
  - `PYTHONPATH=python .venv/bin/python -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector`
    - Result: pass (`Ran 38 tests`, `OK`).
  - `PYTHONPATH=python .venv/bin/python -m unittest tests.python.actions.test_actions_parity`
    - Result: pass (`Ran 93 tests`, `OK`).
  - `PYTHONPATH=python .venv/bin/python -m unittest tests.python.actions.test_actions_parity tests.python.runtime.test_prereq_policy tests.python.runtime.test_command_exit_codes tests.python.runtime.test_cli_packaging tests.python.runtime.test_release_shipability_gate tests.python.runtime.test_release_shipability_gate_cli tests.python.shared.test_validation_workflow_contract tests.python.ui.test_dashboard_rendering_parity tests.python.ui.test_dashboard_orchestrator_restart_selector tests.python.ui.test_textual_selector_responsiveness tests.python.ui.test_interactive_selector_key_throughput_pty tests.python.startup.test_startup_spinner_integration`
    - Result: pass (`Ran 245 tests in 35.237s`, `OK`).

- Config/env/migrations:
  - No new config keys or environment variables.
  - No data/state migrations.
  - Behavior now relies on the existing repo-local `.venv` bootstrap contract when envctl tests run inside envctl repositories/worktrees.

- Risks/notes:
  - The auto-bootstrap preflight is intentionally scoped to envctl repositories/worktrees; other repositories still use their existing configured test commands without side effects.
  - If `pip install -e '.[dev]'` fails because the host is offline or package resolution is broken, envctl now stops with the bootstrap command and first failure detail instead of silently falling through to opaque downstream test failures.
