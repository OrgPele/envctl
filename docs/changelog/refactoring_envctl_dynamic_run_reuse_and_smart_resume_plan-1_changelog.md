# Changelog

## 2026-03-17

### Scope
- Implemented end-to-end run reuse for startup flows using a persisted startup identity fingerprint and stronger project identity matching.
- Extended reuse beyond service-bearing auto-resume so disabled-startup dashboard sessions can reopen the same run when the effective environment matches.
- Reordered startup orchestration so reuse is evaluated before fresh disabled-startup dashboard state is created.

### Key Behavior Changes
- New run reuse support computes a stable startup identity from mode, selected project roots, startup-enabled state, enabled services, enabled dependencies, and backend/frontend directory settings.
- Exact and subset service-bearing reuse still routes through resume truth reconciliation, but now records reopen metadata (`run_reuse_count`, `last_reopened_at`, `last_reuse_reason`) on the reused run.
- Exact disabled-startup dashboard relaunches now reuse the existing `run_id`, refresh the persisted dashboard metadata, and keep a fresh `session_id`.
- Reuse decisions reject mismatched project roots and startup fingerprints, while older states without root metadata still have a weak name-only fallback path.
- Startup identifier output is now announced only after the run decision is resolved, so reused sessions print the reused `run_id` instead of an abandoned fresh one.
- `explain-startup --json` now reports a richer `run_reuse` decision payload, and debug bundle diagnostics aggregate the new run-reuse skip events.

### Files / Modules Touched
- `python/envctl_engine/startup/run_reuse_support.py`
- `python/envctl_engine/runtime/engine_runtime_startup_support.py`
- `python/envctl_engine/startup/startup_orchestrator.py`
- `python/envctl_engine/startup/finalization.py`
- `python/envctl_engine/startup/resume_orchestrator.py`
- `python/envctl_engine/startup/session.py`
- `python/envctl_engine/startup/startup_selection_support.py`
- `python/envctl_engine/runtime/inspection_support.py`
- `python/envctl_engine/debug/debug_bundle_diagnostics.py`
- `tests/python/runtime/test_engine_runtime_startup_support.py`
- `tests/python/startup/test_startup_orchestrator_flow.py`
- `tests/python/runtime/test_engine_runtime_command_parity.py`
- `tests/python/runtime/test_lifecycle_parity.py`
- `tests/python/runtime/test_engine_runtime_real_startup.py`

### Tests Run
- `python3 -m unittest tests.python.runtime.test_engine_runtime_startup_support`
- `python3 -m unittest tests.python.startup.test_startup_orchestrator_flow`
- `python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity`
- `python3 -m unittest tests.python.runtime.test_lifecycle_parity`
- `python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup`
- `python3 -m unittest tests.python.debug.test_debug_bundle_generation`
- `python3 -m unittest tests.python.state.test_state_repository_contract`
- `python3 -m unittest tests.python.shared.test_import_audit`
- `python3 -m unittest tests.python.runtime.test_engine_runtime_startup_support tests.python.startup.test_startup_orchestrator_flow tests.python.runtime.test_engine_runtime_command_parity tests.python.runtime.test_lifecycle_parity tests.python.runtime.test_engine_runtime_real_startup`

Results:
- All listed `unittest` suites passed.
- `python3 -m pytest -q ...` could not be used in this environment because `pytest` is not installed for the available interpreters.

### Config / Env / Migrations
- No schema migrations or repository layout changes.
- Reuse identity now depends on existing startup config inputs such as startup enablement, enabled services/dependencies, and `BACKEND_DIR` / `FRONTEND_DIR`.
- No new required environment variables were introduced.

### Risks / Notes
- Legacy states without persisted startup identity or project root metadata still use a weak compatibility fallback based on project names, so those older states are safer than before but not as strict as newly written ones.
- Dashboard-only reuse is intentionally exact-match only; subset and expansion reuse remain limited to service-bearing runs.

## 2026-03-17 Follow-up

### Scope
- Fixed a runtime-context protocol regression introduced by the dashboard resume path.

### Key Behavior Changes
- `StartupOrchestrator` now routes the dashboard resume save through the context-resolved state repository accessor instead of reaching into `rt.state_repository` directly.
- This restores compliance with the runtime dependency boundary enforced by the repository protocol tests without changing user-facing run reuse behavior.

### Files / Modules Touched
- `python/envctl_engine/startup/startup_orchestrator.py`
- `docs/changelog/refactoring_envctl_dynamic_run_reuse_and_smart_resume_plan-1_changelog.md`

### Tests Run
- `python3 -m unittest tests.python.runtime.test_runtime_context_protocols`
- `python3 -m unittest tests.python.startup.test_startup_orchestrator_flow tests.python.runtime.test_engine_runtime_command_parity tests.python.runtime.test_lifecycle_parity tests.python.runtime.test_engine_runtime_real_startup`

Results:
- All listed suites passed.

### Risks / Notes
- No behavior change beyond dependency-access discipline; this was a structural compliance fix.

## 2026-03-17 Follow-up 2

### Scope
- Fixed dashboard test-target selection so interactive `t` no longer offers or routes into failed-only reruns after the latest saved test run passed cleanly.

### Key Behavior Changes
- Dashboard failed-test scope detection now ignores saved test-history artifacts when the latest `project_test_summaries` entry is marked `status: passed`.
- Failed-only reruns remain available for active failure states, including extraction-failure cases and backward-compatible saved failure metadata.
- Interactive test selection now defaults back to the normal backend/frontend or all-tests options after a clean full-suite pass instead of surfacing a dead-end failed-only action.

### Files / Modules Touched
- `python/envctl_engine/ui/dashboard/orchestrator.py`
- `tests/python/ui/test_dashboard_orchestrator_restart_selector.py`

### Tests Run
- `python3 -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector.DashboardOrchestratorRestartSelectorTests.test_interactive_test_service_selection_hides_failed_rerun_when_latest_status_passed`
- `python3 -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector.DashboardOrchestratorRestartSelectorTests.test_interactive_test_service_selection_offers_failed_rerun_when_saved_failures_exist tests.python.ui.test_dashboard_orchestrator_restart_selector.DashboardOrchestratorRestartSelectorTests.test_interactive_test_service_selection_offers_failed_rerun_when_status_failed_but_count_zero`
- `python3 -m unittest tests.python.ui.test_dashboard_orchestrator_restart_selector`
- `python3 -m unittest tests.python.actions.test_actions_parity.ActionsParityTests.test_test_action_writes_passed_summary_with_no_failed_tests_marker`
- `python3 -m unittest tests.python.actions.test_actions_parity.ActionsParityTests.test_failed_only_rerun_reports_extraction_failure_without_telling_user_to_rerun_full_suite`

Results:
- All listed `unittest` commands passed.

### Config / Env / Migrations
- No config, environment, or migration changes.

### Risks / Notes
- The dashboard still intentionally offers failed-only reruns for latest states that remain marked `failed`, even when rerunnable selectors cannot be reconstructed, so users can still land on the existing explanatory error path for extraction-failure cases.

## 2026-03-17 Follow-up 3

### Scope
- Hardened run-reuse safety around failed resume and plan expansion fallbacks.
- Narrowed dashboard-only reuse so ordinary empty startup-enabled states do not reopen as dashboard sessions.
- Restored `--explain-startup` plan semantics by deriving the inspected startup route from the original CLI arguments instead of forcing `start`.

### Key Behavior Changes
- Failed `resume_exact` / `resume_subset` attempts now restore the startup session to a fresh-run state before continuing, so subsequent startup or failure finalization cannot overwrite the reused candidate run.
- `reuse_expand` now preserves prior services and metadata for the new attempt while keeping a fresh `run_id`, matching the prior isolation semantics for expansion failures.
- Dashboard-only reuse now requires the persisted `dashboard_runs_disabled` marker, preventing normal empty states from being reopened as `resume_dashboard_exact`.
- `--plan --explain-startup ...` now reports plan-specific selection and reuse semantics instead of being modeled as a plain `start`.

### Files / Modules Touched
- `python/envctl_engine/startup/startup_orchestrator.py`
- `python/envctl_engine/startup/run_reuse_support.py`
- `python/envctl_engine/runtime/inspection_support.py`
- `tests/python/startup/test_startup_orchestrator_flow.py`
- `tests/python/runtime/test_engine_runtime_startup_support.py`
- `tests/python/runtime/test_engine_runtime_command_parity.py`

### Tests Run
- `python3 -m unittest tests.python.runtime.test_engine_runtime_startup_support.EngineRuntimeStartupSupportTests.test_run_reuse_rejects_empty_startup_enabled_state_without_dashboard_marker`
- `python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity.EngineRuntimeCommandParityTests.test_explain_startup_json_preserves_plan_selection_semantics`
- `python3 -m unittest tests.python.startup.test_startup_orchestrator_flow.StartupOrchestratorFlowTests.test_resume_reuse_failure_falls_back_to_fresh_run_id_before_failure_write tests.python.startup.test_startup_orchestrator_flow.StartupOrchestratorFlowTests.test_reuse_expand_failure_writes_failed_state_to_fresh_run_id`
- `python3 -m unittest tests.python.startup.test_startup_orchestrator_flow`
- `python3 -m unittest tests.python.runtime.test_engine_runtime_startup_support`
- `python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity`
- `python3 -m unittest tests.python.runtime.test_lifecycle_parity`
- `python3 -m unittest tests.python.runtime.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_exact_tree_plan_match_reuses_prior_run_id tests.python.runtime.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_disabled_tree_dashboard_relaunch_reuses_prior_run_id tests.python.runtime.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_config_profile_change_forces_fresh_run tests.python.runtime.test_engine_runtime_real_startup.EngineRuntimeRealStartupTests.test_project_root_change_forces_fresh_run`

Results:
- All listed `unittest` commands passed.

### Config / Env / Migrations
- No config, environment, or migration changes.

### Risks / Notes
- Service-resume reuse still announces the candidate `run_id` before calling `resume` so successful interactive reuse keeps the reused identifier visible; on failure the session state now rolls back before any fresh-run artifacts are written.

## 2026-03-17 Follow-up 4

### Scope
- Removed order sensitivity from `explain-startup` command parsing so `--explain-startup --plan ...` and `--plan --explain-startup ...` both dispatch through the inspection path.

### Key Behavior Changes
- Once `explain-startup` is present in the parsed command stream, later startup-command tokens still contribute mode and plan flags but no longer steal the top-level command away from direct inspection.
- Plan-inline flags keep forcing trees-mode semantics during parsing even when `explain-startup` owns the final dispatch command.

### Files / Modules Touched
- `python/envctl_engine/runtime/command_router.py`
- `tests/python/runtime/test_cli_router.py`
- `tests/python/runtime/test_engine_runtime_command_parity.py`

### Tests Run
- `python3 -m unittest tests.python.runtime.test_cli_router.CliRouterTests.test_explain_startup_takes_precedence_over_plan_tokens_regardless_of_order`
- `python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity.EngineRuntimeCommandParityTests.test_explain_startup_json_preserves_plan_selection_semantics`
- `python3 -m unittest tests.python.runtime.test_cli_router`
- `python3 -m unittest tests.python.runtime.test_engine_runtime_command_parity`
- `python3 -m unittest tests.python.startup.test_startup_orchestrator_flow tests.python.runtime.test_engine_runtime_startup_support`

Results:
- All listed `unittest` commands passed.

### Config / Env / Migrations
- No config, environment, or migration changes.

### Risks / Notes
- `explain-startup` now has intentional precedence over startup-command aliases during parsing; this is limited to inspection flows and does not change normal `start` / `plan` dispatch when `explain-startup` is absent.
