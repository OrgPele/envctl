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
