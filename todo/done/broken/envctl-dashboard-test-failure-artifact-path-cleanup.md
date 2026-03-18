# Envctl Dashboard Test Failure Artifact Path Cleanup

## Goals / non-goals / assumptions (if relevant)
- Goals:
  - Make the interactive dashboard and test action output show a single saved artifact path for failed test detail instead of echoing redundant inline failure logs.
  - Ensure the file referenced by the dashboard path is complete enough for operators to diagnose suite-level failures, including failures where envctl cannot derive rerunnable selectors.
  - Keep failed-test rerun support (`failed_tests_manifest.json`) intact while improving the operator-facing artifact contract.
- Non-goals:
  - Changing test command selection, parallelism policy, or failed-test rerun semantics beyond the artifact/reporting path.
  - Reworking non-test project action failure reporting (`migrate`, `review`, `pr`, `commit`), which already uses separate `report_path` handling.
  - Changing runtime state root layout outside the existing run-scoped artifact tree.
- Assumptions:
  - The operator-visible problem is the legacy dashboard path because the user repro text matches `python/envctl_engine/ui/dashboard/rendering.py:_print_dashboard_snapshot` output (`Development Environment - Interactive Mode`, `run_id`, `session_id`, `Configured Services`, `tests:`).
  - The desired dashboard behavior is: show the saved artifact path once, keep the dashboard itself concise, and move complete failure context into the saved file behind that path.

## Goal (user experience)
After a failed `test` command from the interactive dashboard, the operator should see one stable `tests:` / `failure summary:` artifact path per affected project and should not see redundant suite log excerpts inline in the dashboard command area. Opening the referenced file should show the complete cleaned failure context for that project, including generic suite failures such as startup/import/configuration crashes where envctl cannot extract rerunnable test selectors.

## Business logic and data model mapping
- Command dispatch and ownership:
  - `python/envctl_engine/runtime/engine_runtime_dispatch.py:dispatch_command` routes action commands to `runtime.action_command_orchestrator.execute(...)`.
  - `python/envctl_engine/runtime/engine_runtime.py:_run_test_action` delegates `test` routes to `ActionCommandOrchestrator.run_test_action(...)`.
  - `python/envctl_engine/actions/action_command_orchestrator.py:run_test_action` delegates execution to `python/envctl_engine/actions/action_test_runner.py:run_test_action`.
- Test execution and failure summarization:
  - `python/envctl_engine/actions/action_test_runner.py:run_test_action` builds per-suite outcomes and currently stores `failure_summary` via `_summarize_failure_output(...)`.
  - `python/envctl_engine/test_output/test_runner.py:TestRunner.run_tests`, `_run_with_streaming(...)` populate parser results and return cleaned subprocess stdout/stderr.
  - `python/envctl_engine/test_output/parser_base.py:TestResult` carries `failed_tests`, `error_details`, and summary counts consumed by artifact persistence.
- Persisted state and artifact model:
  - `python/envctl_engine/state/models.py:RunState.metadata` stores `project_test_summaries`.
  - `python/envctl_engine/actions/action_command_orchestrator.py:_persist_test_summary_artifacts(...)` writes `project_test_summaries`, `project_test_results_root`, and `project_test_results_updated_at`.
  - `python/envctl_engine/actions/action_command_orchestrator.py:_write_failed_tests_summary(...)` writes:
    - `summary_path`: `runs/<run_id>/test-results/<stamp>/<project>/failed_tests_summary.txt`
    - `short_summary_path`: `runs/<run_id>/ft_<digest>.txt`
    - `manifest_path`: `failed_tests_manifest.json`
    - `state_path`: `test_state.txt`
- Dashboard/UI rendering:
  - `python/envctl_engine/actions/action_command_orchestrator.py:_print_test_suite_overview(...)` prints per-project `failure summary:` paths after suite execution.
  - `python/envctl_engine/ui/dashboard/rendering.py:_print_dashboard_project_tests_row(...)` renders the persistent `tests:` dashboard row from `project_test_summaries`.
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_print_test_failure_details(...)` suppresses a detached duplicate block when saved test summaries already exist.

## Current behavior (verified in code)
- Failed test runs already persist per-project artifacts and state metadata:
  - `python/envctl_engine/actions/action_command_orchestrator.py:_persist_test_summary_artifacts(...)` creates a new `test-results/run_<timestamp>/` directory under `runs/<run_id>/`.
  - `python/envctl_engine/actions/action_command_orchestrator.py:_write_failed_tests_summary(...)` writes both `failed_tests_summary.txt` and the shorter `ft_<digest>.txt` alias, then persists those paths into `RunState.metadata["project_test_summaries"]`.
- The dashboard snapshot already knows how to show a path instead of file contents:
  - `python/envctl_engine/ui/dashboard/rendering.py:_print_dashboard_project_tests_row(...)` prints:
    - `✓/✗ tests: (<timestamp>)`
    - the summary path on the next line
  - `tests/python/actions/test_actions_parity.py:test_test_action_persists_failed_test_summary_artifacts...` verifies the dashboard renders `short_summary_path` and does not render the deeper `summary_path` when both are present.
- Interactive dashboard failure handling already avoids a second detached “failure details” block:
  - `python/envctl_engine/ui/dashboard/orchestrator.py:_print_test_failure_details(...)` only checks whether saved summary paths exist and returns `True` so `Command failed (exit 1).` is not printed again.
  - `tests/python/ui/test_dashboard_orchestrator_restart_selector.py:test_interactive_test_failure_with_saved_summary_skips_duplicate_dashboard_failure_block` locks in that suppression.
- The remaining inline noise comes from test action execution, not from the dashboard row:
  - `python/envctl_engine/actions/action_test_runner.py:run_test_action` prints `failure: ...` for every failed suite during interactive runs.
  - `_print_test_suite_overview(...)` then prints `failure summary:` plus the saved artifact path, so the operator sees both the inline excerpt and the saved path.
- The saved failure text is incomplete in generic suite-failure scenarios:
  - `python/envctl_engine/actions/action_test_runner.py:_summarize_failure_output(...)` takes only the first non-empty stream (`stderr` first, else `stdout`) and truncates to the first three non-empty lines.
  - `python/envctl_engine/actions/action_command_orchestrator.py:_collect_generic_suite_failures(...)` persists that already-truncated `failure_summary` when `parsed.failed_tests` is empty.
  - `python/envctl_engine/actions/action_command_orchestrator.py:_format_summary_error_lines(...)` further compacts/truncates lines to a 60-line structured subset before writing the summary file.
  - The generic failure fallback string is currently `Test command failed before envctl could extract failed tests.` if no snippet survives.
- Parser fallback also leaves completeness gaps when output is only on stderr:
  - `python/envctl_engine/test_output/test_runner.py:_run_with_streaming(...)` calls `parser.parse_output(clean_stdout)` when streaming callbacks are unavailable, so stderr-only failure content is not parsed into `TestResult.error_details`.
- Config/docs surface for this behavior is minimal:
  - `docs/reference/configuration.md` documents test execution controls (`ENVCTL_ACTION_TEST_PARALLEL`, `ENVCTL_ACTION_TEST_PARALLEL_MAX`) and dashboard backend policy, but no config key currently governs failed-summary completeness or dashboard artifact-only rendering.
  - `docs/developer/state-and-artifacts.md` establishes `runs/<run_id>/` as the authoritative per-run artifact location.

## Root cause(s) / gaps
- `python/envctl_engine/actions/action_test_runner.py:_summarize_failure_output(...)` is intentionally terse, so generic suite failures lose important detail before they ever reach the persisted summary file.
- `python/envctl_engine/test_output/test_runner.py:_run_with_streaming(...)` ignores `stderr` during non-streaming parser fallback, so stderr-only failures are underrepresented in `TestResult.error_details`.
- `python/envctl_engine/actions/action_test_runner.py:run_test_action` prints inline `failure:` excerpts in interactive mode even though `project_test_summaries` already produce the saved artifact path surfaced by `_print_test_suite_overview(...)` and the dashboard snapshot.
- `python/envctl_engine/ui/dashboard/rendering.py:_print_dashboard_project_tests_row(...)` reads `short_summary_path`/`summary_path` directly instead of reusing the orchestrator’s short-path repair logic, so older state entries without `short_summary_path` can still render the deeper `failed_tests_summary.txt` path.

## Plan
### 1) Define the operator-facing failed-test artifact contract
- Keep `RunState.metadata["project_test_summaries"]` as the canonical dashboard input, but tighten the meaning of the displayed path:
  - the displayed path must always refer to the operator-facing artifact that contains the complete cleaned failure context for that project
  - the dashboard should never need to inline suite logs when that artifact exists
- Confirm the displayed path stays run-scoped under `python/envctl_engine/state/repository.py:RuntimeStateRepository.run_dir_path(...)` / `test_results_dir_path(...)`.
- Preserve rerun selector state in `failed_tests_manifest.json`; do not overload the manifest with dashboard rendering concerns.

### 2) Replace truncated generic failure snippets with complete cleaned project failure content
- Update `python/envctl_engine/actions/action_test_runner.py` so suite outcomes keep a richer failure payload than the current `_summarize_failure_output(...)` three-line snippet.
- Planned implementation shape:
  - add a helper that merges both `stderr` and `stdout` in deterministic order, strips ANSI/progress markers, preserves source labels when both streams are present, and does not drop later lines prematurely
  - keep a short status snippet only for event/status text if needed, but persist the full cleaned failure text in the outcome payload used by `_write_failed_tests_summary(...)`
- Update `python/envctl_engine/actions/action_command_orchestrator.py:_collect_generic_suite_failures(...)` / `_write_failed_tests_summary(...)` so generic suite failures write the full cleaned failure body into the saved artifact instead of the pre-truncated summary.
- For parsed failures (`failed_tests` present), keep the current per-test structure but append enough suite-level context to make the artifact self-sufficient when the extracted per-test snippet is not enough.
- Edge cases to cover explicitly:
  - stderr-only startup/import/config crashes
  - stdout-only framework crashes
  - both streams populated with distinct content
  - failed-only reruns that preserve a previous manifest when selector extraction fails (`preserved_after_failed_only_extraction_failure`)

### 3) Stop printing inline suite failure logs when a saved artifact path will be shown
- Update `python/envctl_engine/actions/action_test_runner.py:run_test_action` to stop printing `failure: ...` excerpts during interactive test execution once the saved summary path is the intended operator-facing surface.
- Keep concise suite status lines (`passed/failed`, counts, duration), but route operators to the persisted file path rather than echoing raw log snippets inline.
- Ensure `_print_test_suite_overview(...)` remains the single post-run textual pointer surface by printing `failure summary:` and the artifact path once per failed project.
- Do not regress non-interactive CLI output for cases where no artifact can be written; the fallback should still surface a failure reason if persistence itself fails.

### 4) Unify dashboard path rendering on the short alias path
- Reuse `python/envctl_engine/ui/dashboard/orchestrator.py:_test_summary_display_path(...)` / `_ensure_short_test_summary_path(...)` from `python/envctl_engine/ui/dashboard/rendering.py:_print_dashboard_project_tests_row(...)` rather than duplicating raw path selection.
- This keeps the interactive dashboard on the stable `ft_<digest>.txt` alias even for older state entries that only persisted `summary_path`.
- Preserve existing cleanup semantics in `python/envctl_engine/runtime/engine_runtime_lifecycle_support.py:_prune_project_metadata(...)` so both the deep summary path and the short alias are still removed on worktree cleanup.

### 5) Close parser fallback gaps that currently hide failure detail
- Update `python/envctl_engine/test_output/test_runner.py:_run_with_streaming(...)` so non-streaming fallback parsing sees the combined cleaned failure output rather than only `clean_stdout`.
- Ensure `TestResult.error_details` can still be populated when pytest/unittest/jest emit critical failure context on stderr.
- Keep progress-marker stripping and parser semantics stable for successful runs.

### 6) Tighten documentation and changelog evidence around the new artifact-only dashboard contract
- Update the relevant changelog and, if repo standards require, the developer docs that describe run-scoped artifacts so they explicitly say:
  - dashboard shows a saved failure artifact path
  - inline dashboard log excerpts are intentionally suppressed
  - the displayed file contains the complete cleaned failure context for the project
- If the artifact contents remain a structured summary plus appended raw context rather than literal raw logs, document that distinction so operators know what to expect.

## Tests (add these)
### Backend tests
- Extend [tests/python/actions/test_actions_parity.py](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_parity.py):
  - add coverage for generic suite failures where stderr and stdout both contain unique content and assert the persisted `failed_tests_summary.txt` / `ft_<digest>.txt` file contains the full cleaned merged context
  - add a regression proving interactive `test` output no longer prints `failure: ...` when `failure summary:` path output is present
  - add coverage for stderr-only generic failures so the saved summary is still complete
  - add coverage preserving failed-only rerun behavior when selector extraction fails but the previous manifest remains authoritative
- Extend [tests/python/test_output/test_test_runner_streaming_fallback.py](/Users/kfiramar/projects/current/envctl/tests/python/test_output/test_test_runner_streaming_fallback.py):
  - add a non-streaming fallback test where all failure detail is in stderr and verify parser results still capture the failure
  - add a fallback test for combined stdout/stderr failure parsing to ensure no stream is silently discarded

### Frontend tests
- Extend [tests/python/ui/test_dashboard_rendering_parity.py](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_dashboard_rendering_parity.py):
  - add a case where only `summary_path` exists and assert dashboard rendering repairs or prefers the short `ft_<digest>.txt` alias path
  - keep current `tests:` row assertions but change them to reflect the stabilized short-path contract when appropriate
- Extend [tests/python/ui/test_dashboard_orchestrator_restart_selector.py](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_dashboard_orchestrator_restart_selector.py):
  - verify interactive test failures still suppress duplicate dashboard-only failure blocks after the inline `failure:` log removal

### Integration/E2E tests
- Prefer expanding [tests/python/actions/test_actions_parity.py](/Users/kfiramar/projects/current/envctl/tests/python/actions/test_actions_parity.py) as the primary integration contract because this bug crosses test execution, artifact persistence, resume state, and dashboard snapshot rendering in one controlled path.
- If a higher-level interactive regression harness is needed, add one focused dashboard-loop test in [tests/python/ui/test_terminal_ui_dashboard_loop.py](/Users/kfiramar/projects/current/envctl/tests/python/ui/test_terminal_ui_dashboard_loop.py) to confirm the post-failure return-to-dashboard flow shows the prompt after the artifact path summary without inline failure log spam.
- No new BATS suite is required unless unit/integration coverage cannot reproduce the exact interactive regression.

## Observability / logging (if relevant)
- Keep existing status events, but separate “operator path pointer” from “diagnostic snippet” semantics:
  - `test.suite.finish` and `test.suite.summary` remain the machine-readable event sources
  - `test.summary.persisted` should continue to emit the persisted run directory
- If implementation introduces a richer outcome field for full failure content, emit a bounded event or metric only for metadata such as:
  - artifact written / skipped
  - bytes/lines captured
  - whether both stdout and stderr contributed
- Avoid emitting the full failure body into runtime events; the artifact file is the intended durable surface.

## Rollout / verification
- Implement in this order:
  1. richer failure capture in `action_test_runner.py`
  2. summary writer updates in `action_command_orchestrator.py`
  3. inline interactive failure-log suppression
  4. dashboard short-path rendering unification
  5. parser fallback fix in `test_runner.py`
- Verification commands for the implementation phase:
  - `./.venv/bin/python -m pytest tests/python/actions/test_actions_parity.py -q`
  - `./.venv/bin/python -m pytest tests/python/ui/test_dashboard_rendering_parity.py tests/python/ui/test_dashboard_orchestrator_restart_selector.py -q`
  - `./.venv/bin/python -m pytest tests/python/test_output/test_test_runner_streaming_fallback.py -q`
- Manual verification target:
  - trigger a known failing `test` command from the interactive dashboard and confirm:
    - dashboard output shows only the failure artifact path, not inline suite logs
    - the referenced `ft_<digest>.txt` file contains the complete cleaned failure context
    - `test --failed` behavior still uses `failed_tests_manifest.json` correctly

## Definition of done
- Interactive dashboard-driven `test` failures no longer dump redundant suite log excerpts inline when a saved failure artifact path exists.
- The path shown in the dashboard/test summary points to a stable run-scoped file that contains complete cleaned failure context for the affected project.
- Generic suite failures that previously produced truncated “suite failed before envctl could extract failed tests” snippets now preserve enough detail for diagnosis.
- Non-streaming parser fallback no longer loses stderr-only failure detail.
- Focused action, dashboard, and parser regression tests cover the new contract.

## Risk register (trade-offs or missing tests)
- Risk: making the artifact “complete” can reintroduce terminal chrome or excessively large files if raw output is copied without cleanup.
  - Mitigation: strip ANSI/progress noise, preserve source labels, and bound only truly pathological output sizes while keeping materially complete failure content.
- Risk: changing summary-file contents could unintentionally break tests or tooling that assumed the older concise summary format.
  - Mitigation: keep headings/path names stable, preserve `failed_tests_manifest.json` as the rerun contract, and update tests/docs for the new content guarantees.
- Risk: suppressing inline `failure:` excerpts could reduce immediate signal when artifact persistence fails.
  - Mitigation: keep an explicit fallback message when summary persistence itself fails or when no saved artifact path is available.

## Open questions (only if unavoidable)
- None. The repo evidence is sufficient to plan the change without blocking clarification.
