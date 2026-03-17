# Envctl Dashboard Test Failure Artifact Path Cleanup

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Make failed `test` runs in the interactive dashboard show one saved artifact path per affected project instead of mixing that path with redundant inline failure excerpts.
  - Ensure the saved file behind the dashboard path is materially complete for suite-level failures, including cases where envctl cannot derive rerunnable failed tests.
  - Keep failed-test rerun support intact through `failed_tests_manifest.json`.
  - Treat this as follow-on work after dynamic run reuse, not as a prerequisite for startup/resume changes.
- Non-goals:
  - Changing run reuse, smart resume, `run_id` reuse, or any startup/session semantics.
  - Reworking non-test project action failures (`migrate`, `review`, `pr`, `commit`), which already use separate failure-report handling.
  - Changing runtime artifact roots outside the existing run-scoped tree.
- Assumptions:
  - The current operator pain remains in the legacy dashboard/test-output path, not in startup orchestration.
  - The desired UX is still: dashboard shows a stable file path once, and the file contains the useful failure detail.

## Goal (user experience)
After a failed dashboard-driven `test` command, the operator should see a clean `tests:` / `failure summary:` path for each failed project and should not need to parse duplicated inline suite logs in the dashboard output. Opening the referenced file should reveal enough cleaned failure context to diagnose the failure, including generic suite crashes and extraction failures.

## Business logic and data model mapping
- Test execution and outcome capture:
  - `python/envctl_engine/actions/action_test_runner.py:run_test_action`
  - `python/envctl_engine/actions/action_test_runner.py:_summarize_failure_output`
  - `python/envctl_engine/test_output/test_runner.py:TestRunner.run_tests`
  - `python/envctl_engine/test_output/test_runner.py:_run_with_streaming`
- Failed-summary persistence:
  - `python/envctl_engine/actions/action_command_orchestrator.py:_persist_test_summary_artifacts`
  - `python/envctl_engine/actions/action_command_orchestrator.py:_write_failed_tests_summary`
  - `python/envctl_engine/actions/action_command_orchestrator.py:_collect_generic_suite_failures`
  - `python/envctl_engine/actions/action_command_orchestrator.py:_print_test_suite_overview`
- Dashboard rendering / failure suppression:
  - `python/envctl_engine/ui/dashboard/rendering.py:_print_dashboard_project_tests_row`
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_print_test_failure_details`
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_test_summary_display_path`
- State/artifact contract:
  - `python/envctl_engine/state/models.py:RunState`
  - `python/envctl_engine/state/repository.py:RuntimeStateRepository.test_results_dir_path`
  - `docs/developer/state-and-artifacts.md`

## Current behavior (verified in code)
- Failed test runs persist both a deep summary path and a short alias path through `project_test_summaries`.
- The dashboard snapshot already renders a `tests:` row that points at the saved file path rather than printing file contents.
- Interactive dashboard failure handling already suppresses a second detached dashboard-only failure block when saved summaries exist.
- Redundant inline failure noise still comes from the test action path itself:
  - `action_test_runner.py:run_test_action` prints per-suite `failure: ...` excerpts during interactive runs.
  - `_print_test_suite_overview(...)` then prints the saved artifact path, so users see both.
- Generic suite-failure detail is still too lossy:
  - `_summarize_failure_output(...)` collapses to the first non-empty stream and only a few lines.
  - `_collect_generic_suite_failures(...)` persists that truncated text for non-parsed failures.
- Non-streaming parser fallback still parses only cleaned stdout, so stderr-only failures can lose useful detail before summary generation.

## Root cause(s) / gaps
- The operator-facing dashboard contract says “see the saved file,” but the test execution path still emits inline failure snippets before that artifact path is shown.
- Generic suite-failure persistence uses a short status snippet rather than a fuller cleaned failure body.
- The dashboard renderer and orchestrator already prefer the short alias path, but older states can still depend on fallback path repair logic that is not shared everywhere.
- Parser fallback underrepresents stderr-only failures, which reduces the quality of saved summaries.

## Plan
### 1) Keep the scope narrow and independent from startup/resume work
- Limit this change to test execution, failed-summary persistence, and dashboard rendering.
- Do not touch:
  - `startup_orchestrator.py`
  - run reuse helpers
  - session/run identity logic
- Document this explicitly in the implementation PR so it stays decoupled from the run-reuse branch.

### 2) Promote the saved failed-summary file to the single operator-facing surface
- Update `python/envctl_engine/actions/action_test_runner.py:run_test_action` so interactive test execution stops printing inline `failure: ...` excerpts once the saved summary path is the intended operator-facing output.
- Keep concise suite status/count/duration lines.
- Keep `_print_test_suite_overview(...)` as the single textual handoff surface by printing the saved `failure summary:` path once per failed project.
- Preserve a fallback inline message only if summary persistence itself fails and no artifact path exists.

### 3) Make generic suite-failure summaries materially complete
- Replace the current truncated `_summarize_failure_output(...)` persistence contract with a richer cleaned failure body for outcome storage.
- Merge stderr/stdout deterministically, strip ANSI/progress noise, preserve source separation where useful, and avoid collapsing to only the first few lines.
- Feed that richer payload into `_collect_generic_suite_failures(...)` and `_write_failed_tests_summary(...)` so the saved file contains enough context for startup/import/configuration crashes and similar non-parsed failures.
- Preserve the existing per-test structure for parsed failures, but allow suite-level context to be appended when needed.

### 4) Close stderr-only parser fallback gaps
- Update `python/envctl_engine/test_output/test_runner.py:_run_with_streaming(...)` so non-streaming fallback parsing sees combined cleaned failure output rather than stdout alone.
- Ensure parsed `error_details` can still be populated when pytest or other runners emit material failure context on stderr.
- Keep successful-run behavior and progress-marker stripping stable.

### 5) Unify dashboard path selection on the short alias path
- Reuse `_test_summary_display_path(...)` / `_ensure_short_test_summary_path(...)` from the orchestrator inside the dashboard rendering path so the UI consistently prefers `ft_<digest>.txt`.
- Keep cleanup semantics unchanged so both the deep summary path and short alias are still removed by existing lifecycle cleanup logic.

### 6) Update docs/changelog for the artifact-only dashboard contract
- Clarify in the relevant changelog/docs that:
  - the dashboard points to the saved failure artifact
  - inline suite log spam is intentionally suppressed
  - the saved file is expected to contain cleaned diagnostic context, not just rerun metadata

## Tests (add these)
### Backend tests
- Extend [tests/python/actions/test_actions_parity.py](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_parity.py):
  - generic suite failure with distinct stdout/stderr content persists the full cleaned merged context
  - interactive `test` output no longer prints `failure: ...` when the saved summary path is shown
  - stderr-only generic failures still produce a useful saved summary
  - failed-only rerun behavior remains unchanged when selector extraction fails
- Extend [tests/python/test_output/test_test_runner_streaming_fallback.py](/Users/kfiramar/projects/current/envctl/tests/python/test_output/test_test_runner_streaming_fallback.py):
  - stderr-only failure parsing in non-streaming fallback
  - combined stdout/stderr fallback parsing

### Frontend tests
- Extend [tests/python/ui/test_dashboard_rendering_parity.py](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_dashboard_rendering_parity.py):
  - renderer prefers or repairs to the short alias path when only `summary_path` is present
- Extend [tests/python/ui/test_dashboard_orchestrator_restart_selector.py](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_dashboard_orchestrator_restart_selector.py):
  - interactive test failures still suppress duplicate dashboard-only failure blocks after inline failure-log removal

### Integration/E2E tests
- Prefer extending [tests/python/actions/test_actions_parity.py](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_parity.py) as the main integration contract because it already spans test execution, summary persistence, state update, and dashboard snapshot rendering.
- Add one focused dashboard-loop regression in [tests/python/ui/test_terminal_ui_dashboard_loop.py](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_terminal_ui_dashboard_loop.py) only if needed to prove the post-failure return-to-dashboard flow remains clean.

## Observability / logging (if relevant)
- Keep existing machine-readable events such as `test.suite.finish`, `test.suite.summary`, and `test.summary.persisted`.
- If richer failure-body capture is added, emit only bounded metadata about artifact creation and capture source composition; do not emit the full failure body into events.

## Rollout / verification
- Implement in this order:
  1. richer failure-body capture in `action_test_runner.py`
  2. summary writer updates in `action_command_orchestrator.py`
  3. inline interactive failure-log suppression
  4. dashboard short-path unification
  5. parser fallback fix in `test_runner.py`
- Verification commands:
  - `./.venv/bin/python -m pytest tests/python/actions/test_actions_parity.py -q`
  - `./.venv/bin/python -m pytest tests/python/ui/test_dashboard_rendering_parity.py tests/python/ui/test_dashboard_orchestrator_restart_selector.py -q`
  - `./.venv/bin/python -m pytest tests/python/test_output/test_test_runner_streaming_fallback.py -q`
- Manual verification:
  - trigger a known failing dashboard `test` run
  - confirm the dashboard shows the saved path without inline suite log spam
  - confirm the referenced summary file contains useful cleaned detail
  - confirm `test --failed` still uses `failed_tests_manifest.json` correctly

## Definition of done
- Dashboard-driven `test` failures no longer print redundant inline suite failure excerpts when a saved artifact path exists.
- The displayed path resolves to a stable run-scoped file that contains materially complete cleaned failure detail for the affected project.
- Generic suite failures preserve enough diagnostic detail for operators to debug without reading raw terminal noise.
- Parser fallback no longer loses stderr-only failure detail.
- Focused action, dashboard, and parser regressions cover the new contract.

## Risk register (trade-offs or missing tests)
- Risk: making saved summaries more complete can reintroduce terminal chrome or excessively large files.
  - Mitigation: strip ANSI/progress noise and bound only pathological output while keeping materially useful context.
- Risk: changing summary contents can break tests or tooling that assumed the old terse format.
  - Mitigation: keep file names and manifest semantics stable; update tests/docs that rely on summary content.
- Risk: removing inline failure excerpts can reduce immediate signal if artifact persistence fails.
  - Mitigation: keep an explicit fallback inline error only when no artifact path can be produced.

## Open questions (only if unavoidable)
- None.
