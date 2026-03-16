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

## 2026-03-16 - Remove duplicate interactive test failure replay

- Scope:
  - Cleaned up interactive dashboard test output after failed `t` runs so envctl no longer prints the same saved failure excerpt twice.

- Key behavior changes:
  - `python/envctl_engine/ui/dashboard/orchestrator.py`
    - Interactive `test` commands now skip the detached `Test failure summary for <project>` replay block when the just-finished test action already produced a saved failure summary.
    - The dashboard snapshot/test row still retains the compact saved excerpt; only the immediate duplicate replay after the `Test Suite Summary` block is suppressed.
  - `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`
    - Updated regression coverage to assert the interactive loop no longer replays a duplicate failure-summary block after a failed test action.

- Files/modules touched:
  - `python/envctl_engine/ui/dashboard/orchestrator.py`
  - `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`
  - `docs/changelog/broken_envctl_release_readiness_closure_plan-1_changelog.md`

- Tests run + results:
  - `PYTHONPATH=python .venv/bin/python -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector`
    - Result: pass (`Ran 38 tests`, `OK`).
  - `PYTHONPATH=python .venv/bin/python -m unittest tests.python.ui.test_dashboard_rendering_parity tests.python.actions.test_actions_parity`
    - Result: pass (`Ran 106 tests`, `OK`).

- Config/env/migrations:
  - No config or environment changes.
  - No migrations.

- Risks/notes:
  - If a future test-action failure occurs before envctl can persist any saved summary metadata, the generic failure path still applies so failures remain visible rather than being silently suppressed.

## 2026-03-16 - Trim interactive test suite failure summary noise

- Scope:
  - Cleaned up the `Test Suite Summary` block for failed interactive test actions so it no longer dumps saved failure excerpt lines inline.

- Key behavior changes:
  - `python/envctl_engine/actions/action_command_orchestrator.py`
    - The per-project `failure summary:` section printed by the test action now shows only the saved summary path.
    - Saved excerpt metadata is still persisted and remains available to dashboard snapshot rendering.
  - `tests/python/actions/test_actions_parity.py`
    - Added regression coverage proving failed test action output keeps the saved path but omits the verbose failed-test/explanation lines.

- Files/modules touched:
  - `python/envctl_engine/actions/action_command_orchestrator.py`
  - `tests/python/actions/test_actions_parity.py`
  - `docs/changelog/broken_envctl_release_readiness_closure_plan-1_changelog.md`

- Tests run + results:
  - `PYTHONPATH=python .venv/bin/python -m unittest tests.python.actions.test_actions_parity.ActionsParityTests.test_test_action_writes_failed_tests_summary_and_persists_dashboard_metadata`
    - Result: pass (`Ran 1 test`, `OK`).
  - `PYTHONPATH=python .venv/bin/python -m unittest tests.python.ui.test_dashboard_rendering_parity tests.python.ui.test_dashboard_orchestrator_restart_selector`
    - Result: pass (`Ran 51 tests`, `OK`).

- Config/env/migrations:
  - No config or environment changes.
  - No migrations.

- Risks/notes:
  - The immediate action output is now quieter by design; the richer excerpt still exists in the saved summary file and dashboard snapshot when deeper inspection is needed.

## 2026-03-16 - Harden wrapper-path intent against stale argv0 env leakage

- Scope:
  - Fixed packaging/launcher regressions where explicit wrapper invocations could be misclassified as bare `envctl` intent because the wrapper’s internal preserved-argv0 env var leaked into later test processes.

- Key behavior changes:
  - `bin/envctl`
    - Added a dedicated re-exec marker so preserved original `argv0` is only trusted during the wrapper’s own Python-version re-exec chain.
    - Supported-runtime launches now clear stale inherited wrapper-preservation env state instead of propagating it into child commands and tests.
  - `python/envctl_engine/runtime/launcher_support.py`
    - `is_explicit_wrapper_path(...)` now ignores ambient preserved-argv0 state unless the caller explicitly supplies an environment map.
    - Real wrapper flows still preserve the intended redirect behavior because `bin/envctl` continues to pass `os.environ` explicitly.
  - `tests/python/runtime/test_cli_packaging.py`
    - Added regressions for ambient/stale preserved-argv0 leakage in both direct helper calls and explicit-wrapper subprocess launches.

- Files/modules touched:
  - `bin/envctl`
  - `python/envctl_engine/runtime/launcher_support.py`
  - `tests/python/runtime/test_cli_packaging.py`
  - `docs/changelog/broken_envctl_release_readiness_closure_plan-1_changelog.md`

- Tests run + results:
  - `PYTHONPATH=python .venv/bin/python -m unittest tests.python.runtime.test_cli_packaging.CliPackagingTests.test_explicit_absolute_wrapper_path_skips_shadow_redirect tests.python.runtime.test_cli_packaging.CliPackagingTests.test_explicit_symlink_wrapper_path_is_treated_as_wrapper_intent tests.python.runtime.test_cli_packaging.CliPackagingTests.test_explicit_wrapper_path_ignores_ambient_preserved_argv0_without_explicit_env tests.python.runtime.test_cli_packaging.CliPackagingTests.test_explicit_wrapper_subprocess_skips_shadowed_installed_envctl tests.python.runtime.test_cli_packaging.CliPackagingTests.test_explicit_wrapper_subprocess_ignores_stale_preserved_argv0_env`
    - Result: pass (`Ran 5 tests`, `OK`).
  - `PYTHONPATH=python .venv/bin/python -m unittest tests.python.runtime.test_cli_packaging`
    - Result: pass (`Ran 24 tests in 13.937s`, `OK`).

- Config/env/migrations:
  - No user-facing config changes.
  - Added an internal wrapper re-exec marker env var only for the wrapper’s own transient process chain.
  - No migrations.

- Risks/notes:
  - The fix intentionally narrows trust in inherited wrapper env state; if future launcher flows need preserved original `argv0`, they must pass an explicit env map or participate in the wrapper’s marked re-exec path.

## 2026-03-16 - Collapse dashboard service log label and path onto one line

- Scope:
  - Cleaned up dashboard service rows so `log:` and the resolved log path render on one line instead of two.

- Key behavior changes:
  - `python/envctl_engine/ui/dashboard/rendering.py`
    - Service rows now print `log: <path>` on a single line.
    - No other dashboard service-row formatting changed.
  - `tests/python/ui/test_dashboard_rendering_parity.py`
    - Added regression coverage for the single-line log rendering contract.

- Files/modules touched:
  - `python/envctl_engine/ui/dashboard/rendering.py`
  - `tests/python/ui/test_dashboard_rendering_parity.py`
  - `docs/changelog/broken_envctl_release_readiness_closure_plan-1_changelog.md`

- Tests run + results:
  - `PYTHONPATH=python .venv/bin/python -m unittest tests.python.ui.test_dashboard_rendering_parity`
    - Result: pass (`Ran 14 tests in 0.155s`, `OK`).

- Config/env/migrations:
  - No config or environment changes.
  - No migrations.

- Risks/notes:
  - Long log paths remain unwrapped; this change only removes the extra line break between the label and the path.
