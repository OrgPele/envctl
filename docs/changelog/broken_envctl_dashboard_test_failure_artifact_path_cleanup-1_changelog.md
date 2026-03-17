## 2026-03-17 - Failed test artifact path cleanup

### Scope
Implemented the interactive dashboard failed-test artifact cleanup from `MAIN_TASK.md` so dashboard-driven test failures point to one saved artifact path per project, inline suite failure excerpts are suppressed, and the saved file now keeps enough cleaned suite context to diagnose generic failures.

### Key behavior changes
- `python/envctl_engine/actions/action_test_runner.py`
  - added cleaned failure-body capture that merges `stderr` and `stdout` in deterministic order for persisted artifacts
  - kept the short failure snippet for status/error text, but stopped printing inline interactive `failure:` excerpts next to suite rows
  - persisted richer `failure_details` alongside the existing per-suite outcome payload
- `python/envctl_engine/actions/action_command_orchestrator.py`
  - generic suite failures now write the full cleaned failure body into the saved summary artifact instead of the old three-line snippet
  - parsed failures keep the per-test structure and now append suite-level context so the artifact remains self-sufficient
  - preserved failed-only rerun manifest behavior when selector extraction still fails
- `python/envctl_engine/test_output/test_runner.py`
  - non-streaming fallback parsing now sees both `stdout` and `stderr`
  - run-only fallback now streams stderr lines through the parser instead of silently discarding them
- `python/envctl_engine/ui/dashboard/rendering.py`
  - dashboard `tests:` rows now reuse the orchestrator short-path repair logic so older state entries render the stable `ft_<digest>.txt` alias
- `docs/developer/state-and-artifacts.md`
  - documented the operator-facing failed-test artifact contract and the short-alias dashboard behavior

### Files / modules touched
- `python/envctl_engine/actions/action_test_runner.py`
- `python/envctl_engine/actions/action_command_orchestrator.py`
- `python/envctl_engine/test_output/test_runner.py`
- `python/envctl_engine/ui/dashboard/rendering.py`
- `tests/python/actions/test_actions_parity.py`
- `tests/python/ui/test_dashboard_rendering_parity.py`
- `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`
- `tests/python/test_output/test_test_runner_streaming_fallback.py`
- `docs/developer/state-and-artifacts.md`
- `docs/changelog/broken_envctl_dashboard_test_failure_artifact_path_cleanup-1_changelog.md`

### Tests run + results
- `PYTHONPATH=python python3 -m unittest tests.python.actions.test_actions_parity`
  - result: `Ran 95 tests`, `OK`
- `PYTHONPATH=python python3 -m unittest tests.python.ui.test_dashboard_rendering_parity tests.python.ui.test_dashboard_orchestrator_restart_selector`
  - result: `Ran 52 tests`, `OK`
- `PYTHONPATH=python python3 -m unittest tests.python.test_output.test_test_runner_streaming_fallback`
  - result: `Ran 12 tests`, `OK (skipped=1)`

### Config / env / migrations
- No migrations.
- No new user-facing config keys.
- The dashboard artifact contract still stays under the existing run-scoped runtime tree.

### Risks / notes
- Suite-context capture is intentionally cleaned before persistence, so operators get a diagnostic artifact rather than verbatim raw logs. If a future parser depends on unfiltered terminal chrome, it should read the underlying subprocess streams directly instead of this summary file.
- The targeted verification used `unittest` because the repo-local `.venv` and `pytest` entrypoint referenced in `MAIN_TASK.md` were not present in this worktree.

## 2026-03-17 - Follow-up: inline dashboard test artifact row formatting

### Scope
Adjusted the dashboard `tests:` row formatting so the artifact path and timestamp render on the same line, with the timestamp moved to the end of the path line.

### Key behavior changes
- `python/envctl_engine/ui/dashboard/rendering.py`
  - `tests:` rows now render as `✓/✗ tests: <short-path> (<timestamp>)`
  - removed the extra newline that previously printed the summary path on its own line
- `tests/python/ui/test_dashboard_rendering_parity.py`
  - updated rendering assertions to require the single-line path-plus-timestamp contract for both passed and failed statuses

### Files / modules touched
- `python/envctl_engine/ui/dashboard/rendering.py`
- `tests/python/ui/test_dashboard_rendering_parity.py`
- `docs/changelog/broken_envctl_dashboard_test_failure_artifact_path_cleanup-1_changelog.md`

### Tests run + results
- `PYTHONPATH=python python3 -m unittest tests.python.ui.test_dashboard_rendering_parity`
  - result: `Ran 14 tests`, `OK`

### Config / env / migrations
- No migrations.
- No config changes.

### Risks / notes
- This is a presentation-only change for the dashboard snapshot row; summary excerpt rendering remains unchanged below that line.
